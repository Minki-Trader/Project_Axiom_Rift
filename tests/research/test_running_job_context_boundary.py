from __future__ import annotations

import ast
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

import axiom_rift.operations.running_job_context as context_module
from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.running_job_context import (
    RunningJobExecutionContext,
    running_job_execution_context_dependency_manifest,
    running_job_execution_context_dependency_paths,
    running_job_execution_context_implementation_sha256,
)
from axiom_rift.operations.running_job import (
    RunningJobAuthority,
    RunningJobAuthorityError,
    RunningJobAuthorityIntegrityError,
    RunningJobExecution,
    effective_running_job_implementation,
)
from axiom_rift.research.historical_study_registry import (
    HISTORICAL_HARDCODED_CONTROL_MODULE_SHA256,
)
from axiom_rift.research.historical_adjudication import ReplayPriority
from axiom_rift.research.historical_family_binding import (
    ControlBinding,
    HistoricalFamilyAuthority,
    HistoricalFamilySpec,
    HistoricalMemberSpec,
)
from axiom_rift.research.portfolio import (
    BatchSpec,
    ConcurrentFamilyEvaluationMode,
    ConcurrentFamilyManifest,
)
from axiom_rift.research.replay_obligation import (
    HistoricalReplayObligation,
    ReplayExecutionBinding,
)
from axiom_rift.research.replay_satisfaction_invalidation import (
    ReplayMultiplicityBindingDefect,
    ReplayMultiplicityDefectCode,
    ReplaySatisfactionInvalidationAuditManifest,
    ReplaySelectionFamilyObservation,
    SELECTION_CRITERION_ID,
)
from axiom_rift.storage.evidence import EvidenceStore
from axiom_rift.storage.index import IndexRecord, LocalIndex


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
RESEARCH_ROOT = SOURCE_ROOT / "axiom_rift" / "research"
CONTEXT_PATH = (
    SOURCE_ROOT / "axiom_rift" / "operations" / "running_job_context.py"
).resolve()
RUNNING_JOB_PATH = (
    SOURCE_ROOT / "axiom_rift" / "operations" / "running_job.py"
).resolve()
WRITER_PATH = (
    SOURCE_ROOT / "axiom_rift" / "operations" / "writer.py"
).resolve()
HISTORICAL_RESEARCH_FILES = frozenset(
    HISTORICAL_HARDCODED_CONTROL_MODULE_SHA256
)


def _tracked_research_paths() -> tuple[Path, ...]:
    """Enumerate the exact Git-indexed research surface, never user files."""

    completed = subprocess.run(
        [
            "git",
            "ls-files",
            "-z",
            "--",
            "src/axiom_rift/research/*.py",
        ],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
    )
    return tuple(
        REPOSITORY_ROOT / raw.decode("ascii")
        for raw in completed.stdout.split(b"\0")
        if raw
    )


def _constant_dict_pairs(node: ast.Dict) -> dict[str, str]:
    return {
        key.value: value.value
        for key, value in zip(node.keys, node.values)
        if isinstance(key, ast.Constant)
        and isinstance(key.value, str)
        and isinstance(value, ast.Constant)
        and isinstance(value.value, str)
    }


def _write_test_foundation(root: Path, *, prior_floor: int = 7) -> None:
    foundation = root / "foundation"
    foundation.mkdir(parents=True, exist_ok=True)
    identity_domain = "running-job-context-test"
    identity_inputs = {"fixture": "temporary-foundation"}
    identity = canonical_digest(
        domain=identity_domain,
        payload=identity_inputs,
    )
    (foundation / "data_exposure.yaml").write_text(
        "observed_development_material:\n"
        f"  identity: {identity}\n"
        f"  identity_domain: {identity_domain}\n"
        "  identity_inputs:\n"
        "    fixture: temporary-foundation\n"
        f"  prior_global_multiplicity_floor: {prior_floor}\n",
        encoding="ascii",
    )
    (foundation / "prior_scientific_memory.yaml").write_text(
        "scheduler_weight: none\n"
        "reuse_rule: explicit identity equivalence required\n"
        "warnings: []\n",
        encoding="ascii",
    )


def _fixed_hold_historical_family() -> HistoricalFamilySpec:
    references = tuple(
        f"executable:{ordinal:064x}" for ordinal in range(1, 5)
    )
    members = tuple(
        HistoricalMemberSpec(
            ordinal=ordinal,
            configuration_id=f"configuration-{ordinal}",
            historical_reference_executable_id=references[ordinal - 1],
            parameters={"fixture_slot": ordinal},
        )
        for ordinal in range(1, 5)
    )
    opposite_indices = (1, 0, 3, 2)
    feature_indices = (2, 2, 0, 0)
    controls = tuple(
        ControlBinding(
            subject_historical_executable_id=reference,
            opposite_historical_executable_id=(
                references[opposite_indices[index]]
            ),
            feature_historical_executable_ids=(
                references[feature_indices[index]],
            ),
        )
        for index, reference in enumerate(references)
    )
    return HistoricalFamilySpec(
        original_study_id="STU-8001",
        original_batch_id="batch:" + "8" * 64,
        target_historical_executable_id=references[-1],
        members=members,
        controls=controls,
    )


def _invalidation_manifest(
    obligation: HistoricalReplayObligation,
    family: HistoricalFamilySpec,
) -> ReplaySatisfactionInvalidationAuditManifest:
    references = tuple(
        member.historical_reference_executable_id
        for member in family.members
    )
    observations = []
    for ordinal, reference in enumerate(references, start=1):
        ordered_member_ids = (reference,)
        family_registration_hash = canonical_digest(
            domain="scientific-v2-multiplicity-family",
            payload={
                "alpha_ppm": 50_000,
                "family_id": "fixture-invalid-singleton-family",
                "family_size": 1,
                "method": "holm",
                "ordered_member_ids": list(ordered_member_ids),
                "schema": "scientific_multiplicity_family_registration.v1",
            },
        )
        observations.append(
            ReplaySelectionFamilyObservation(
                executable_id=reference,
                completion_record_id=f"{20 + ordinal:064x}",
                family_id="fixture-invalid-singleton-family",
                family_size=1,
                method="holm",
                alpha_ppm=50_000,
                registered_member_id=reference,
                ordered_member_ids=ordered_member_ids,
                family_registration_hash=family_registration_hash,
            )
        )
    defect = ReplayMultiplicityBindingDefect(
        code=(
            ReplayMultiplicityDefectCode.SELECTION_FAMILY_SIZE_MISMATCH
        ),
        criterion_id=SELECTION_CRITERION_ID,
        batch_open_record_id="batch:" + "b" * 64,
        batch_close_record_id="c" * 64,
        expected_executable_ids=references,
        expected_family_size=len(references),
        observations=tuple(observations),
    )
    return ReplaySatisfactionInvalidationAuditManifest(
        governing_mission_id=obligation.governing_mission_id,
        obligation_id=obligation.identity,
        satisfaction_record_id=(
            "historical-replay-satisfaction:" + "5" * 64
        ),
        satisfaction_event_sequence=2,
        portfolio_decision_id="decision:" + "6" * 64,
        replay_study_id="STU-INVALID-SATISFACTION",
        replay_executable_id=family.target_historical_executable_id,
        replay_study_close_record_id="7" * 64,
        study_diagnosis_id="diagnosis:" + "8" * 64,
        completion_record_ids=tuple(
            observation.completion_record_id
            for observation in observations
        ),
        defect=defect,
    )


def _build_fixed_hold_replay_projection(
    root: Path,
    *,
    prefix_length: int,
    tamper: str | None = None,
) -> SimpleNamespace:
    if prefix_length not in {1, 2, 3, 4}:
        raise ValueError("fixture prefix must select one family ordinal")
    _write_test_foundation(root, prior_floor=7)
    index_path = root / "fixed-hold-projection.sqlite"
    mission_id = "MIS-TEMP"
    study_id = "STU-TEMP-REPLAY"
    family = _fixed_hold_historical_family()
    historical_references = tuple(
        member.historical_reference_executable_id
        for member in family.members
    )
    obligation = HistoricalReplayObligation(
        governing_mission_id=mission_id,
        historical_adjudication_id=(
            "historical-adjudication:" + "a" * 64
        ),
        replay_priority=ReplayPriority.P1,
        original_study_id=family.original_study_id,
        original_study_close_record_id="b" * 64,
        original_completion_record_id="c" * 64,
        original_executable_id=family.target_historical_executable_id,
        audit_artifact_hash="d" * 64,
        validation_plan_hash="e" * 64,
        measurement_artifact_hash="f" * 64,
        claim_ids=("claim-fixture",),
        criterion_ids=(SELECTION_CRITERION_ID,),
        reason_codes=("selection-family-mismatch",),
    )
    family_authority = HistoricalFamilyAuthority(
        replay_obligation_id=obligation.identity,
        family=family,
        reconstruction_source_path=(
            "src/axiom_rift/research/historical_fixture.py"
        ),
        reconstruction_source_sha256="1" * 64,
    )

    registered_reference_order = list(historical_references)
    if tamper == "non_prefix":
        registered_reference_order[0], registered_reference_order[1] = (
            registered_reference_order[1],
            registered_reference_order[0],
        )
    executable_payloads = tuple(
        {
            "component_manifests": [
                {
                    "spec": {
                        "parameter_fields": [
                            "historical_reference_executable_id"
                        ]
                    }
                }
            ],
            "fixture_slot": ordinal,
            "parameters": {
                "historical_reference_executable_id": reference
            },
            "schema": "fixture_executable.v1",
        }
        for ordinal, reference in enumerate(
            registered_reference_order,
            start=1,
        )
    )
    prospective_ids = tuple(
        "executable:"
        + canonical_digest(domain="executable", payload=payload)
        for payload in executable_payloads
    )
    proposal = {
        "candidate_eligible": False,
        "concurrent_family": family.manifest(),
        "historical_family_authority_id": family_authority.identity,
        "historical_family_identity": family.identity,
        "historical_obligation_id": obligation.identity,
        "mechanism": "fixture-fixed-hold",
        "original_study_id": family.original_study_id,
    }
    question = {"causal_question": "fixture replay authority"}
    question_hash = canonical_digest(
        domain="study-question",
        payload=question,
    )
    portfolio_decision_id = "decision:" + "d" * 64
    controlled_chassis = {"schema": "fixture_controlled_chassis.v1"}
    study_payload = {
        "controlled_chassis": controlled_chassis,
        "material_identity": "fixture-material",
        "mission_id": mission_id,
        "portfolio_axis_id": "axis-fixture-replay",
        "portfolio_axis_identity": "axis-identity-fixture",
        "portfolio_decision_id": portfolio_decision_id,
        "question": question,
        "question_hash": question_hash,
        "replay_obligation_ids": [obligation.identity],
        "semantic_proposal": proposal,
    }
    study_hash = canonical_digest(
        domain="study-input",
        payload={
            "controlled_chassis": controlled_chassis,
            "question_hash": question_hash,
            "material_identity": study_payload["material_identity"],
            "portfolio_axis_id": study_payload["portfolio_axis_id"],
            "portfolio_axis_identity": study_payload[
                "portfolio_axis_identity"
            ],
            "portfolio_decision_id": portfolio_decision_id,
            "semantic_proposal": proposal,
        },
    )
    study = IndexRecord(
        kind="study-open",
        record_id=study_id,
        subject=f"Study:{study_id}",
        status="open",
        fingerprint=study_hash,
        payload=study_payload,
    )
    concurrent_family = ConcurrentFamilyManifest(
        evaluation_mode=ConcurrentFamilyEvaluationMode.VECTORIZED,
        executable_ids=tuple(sorted(prospective_ids)),
    )
    batch_spec = BatchSpec(
        batch_id="BAT-TEMP-REPLAY",
        study_id=study_id,
        study_hash=study_hash,
        display_name="fixture fixed-hold replay",
        max_trials=4,
        max_compute_seconds=40,
        max_wall_seconds=80,
        stop_rule="stop only after the exact registered family",
        source_contract_ids=(),
        concurrent_family=concurrent_family,
        acceptance_profile={
            "candidate_authority": "none",
            "exact_original_criteria": list(obligation.criterion_ids),
            "historical_family_authority_id": family_authority.identity,
            "historical_family_identity": family.identity,
            "replay_obligation_id": obligation.identity,
        },
        adaptive_basis={
            "uncertainty": "fixture",
            "causal_complexity": "fixture",
            "surface_curvature": "fixed",
            "compute_cost": "bounded",
            "expected_information_value": "fixture",
            "portfolio_opportunity_cost": "fixture",
        },
    )
    batch_digest = batch_spec.identity.removeprefix("batch:")
    batch = IndexRecord(
        kind="batch-open",
        record_id=batch_spec.identity,
        subject=f"Study:{study_id}",
        status="open",
        fingerprint=batch_digest,
        payload={
            "batch_hash": batch_digest,
            "spec": batch_spec.to_identity_payload(),
        },
        event_stream=f"study-batches:{study_id}",
        event_sequence=1,
    )

    obligation_stream = (
        f"historical-replay-obligation:{obligation.identity}"
    )
    initial = IndexRecord(
        kind="historical-replay-obligation",
        record_id=obligation.identity,
        subject=f"Mission:{mission_id}",
        status="pending",
        fingerprint=obligation.identity.removeprefix(
            "historical-replay-obligation:"
        ),
        payload={"obligation": obligation.to_identity_payload()},
        event_stream=obligation_stream,
        event_sequence=1,
    )
    manifest = _invalidation_manifest(obligation, family)
    satisfaction = IndexRecord(
        kind="historical-replay-obligation-resolution",
        record_id=manifest.satisfaction_record_id,
        subject=f"Mission:{mission_id}",
        status="satisfied",
        fingerprint=manifest.satisfaction_record_id.removeprefix(
            "historical-replay-satisfaction:"
        ),
        payload={
            "obligation_id": obligation.identity,
            "prior_status": "pending",
        },
        event_stream=obligation_stream,
        event_sequence=2,
    )
    audit_manifest_hash = sha256(
        canonical_bytes(manifest.to_identity_payload())
    ).hexdigest()
    invalidation_payload = {
        "audit_manifest": manifest.to_identity_payload(),
        "audit_manifest_hash": audit_manifest_hash,
        "candidate_delta": 0,
        "holdout_reveal_delta": 0,
        "obligation_id": obligation.identity,
        "prior_satisfaction_record_id": manifest.satisfaction_record_id,
        "prior_status": "satisfied",
        "scientific_claim_delta": 0,
        "scientific_satisfaction_delta": 0,
        "scientific_trial_delta": 0,
        "terminal_credit_delta": 0,
    }
    invalidation_event_id = "3" * 64
    invalidation = IndexRecord(
        kind="historical-replay-satisfaction-invalidation",
        record_id=manifest.identity,
        subject=f"Mission:{mission_id}",
        status="pending",
        fingerprint=manifest.identity.removeprefix(
            "historical-replay-satisfaction-invalidation:"
        ),
        payload=invalidation_payload,
        event_stream=obligation_stream,
        event_sequence=3,
        authority_sequence=3,
        authority_event_id=invalidation_event_id,
        authority_offset=300,
    )
    family_record = IndexRecord(
        kind="historical-family-authority",
        record_id=family_authority.identity,
        subject=f"ReplayObligation:{obligation.identity}",
        status="accepted",
        fingerprint=family_authority.identity.removeprefix(
            "historical-family-authority:"
        ),
        payload=family_authority.to_identity_payload(),
        authority_sequence=3,
        authority_event_id=(
            "9" * 64
            if tamper == "family_cross_event"
            else invalidation_event_id
        ),
        authority_offset=300,
    )
    invalidation_result = {
        "audit_manifest_hash": audit_manifest_hash,
        "candidate_delta": 0,
        "historical_family_authority_id": (
            "historical-family-authority:" + "0" * 64
            if tamper == "invalidation_result"
            else family_authority.identity
        ),
        "holdout_reveal_delta": 0,
        "invalidated_satisfaction_record_id": manifest.satisfaction_record_id,
        "pending_replay_obligation_ids": [obligation.identity],
        "replay_obligation_id": obligation.identity,
        "scientific_claim_delta": 0,
        "scientific_satisfaction_delta": 0,
        "scientific_trial_delta": 0,
        "terminal_credit_delta": 0,
    }
    invalidation_operation_id = "fixture-invalidation-operation"
    invalidation_operation = IndexRecord(
        kind="operation",
        record_id=invalidation_operation_id,
        subject=f"Mission:{mission_id}",
        status="success",
        fingerprint="fixture-invalidation-operation",
        payload={
            "event_kind": "historical_replay_satisfaction_invalidated",
            "result": invalidation_result,
        },
        authority_sequence=3,
        authority_event_id=invalidation_event_id,
        authority_offset=300,
    )
    invalidation_journal_event = IndexRecord(
        kind="journal-event",
        record_id=invalidation_event_id,
        subject=f"Mission:{mission_id}",
        status="historical_replay_satisfaction_invalidated",
        fingerprint=invalidation_event_id,
        payload={"operation_id": invalidation_operation_id},
        event_stream="control",
        event_sequence=3,
        authority_sequence=3,
        authority_event_id=invalidation_event_id,
        authority_offset=300,
    )

    trials = []
    for ordinal in range(1, len(prospective_ids) + 1):
        executable_id = prospective_ids[ordinal - 1]
        authority_sequence = 3 + ordinal
        trials.append(
            IndexRecord(
                kind="trial",
                record_id=executable_id,
                subject=f"Batch:{batch_spec.identity}",
                status="evaluated",
                fingerprint=executable_id.removeprefix("executable:"),
                payload={
                    "executable": executable_payloads[ordinal - 1],
                    "study_id": study_id,
                },
                event_stream=f"batch-trials:{batch_spec.identity}",
                event_sequence=ordinal,
                authority_sequence=authority_sequence,
                authority_event_id=f"{authority_sequence:064x}",
                authority_offset=authority_sequence * 100,
            )
        )

    records = [
        initial,
        satisfaction,
        invalidation,
        family_record,
        invalidation_operation,
        invalidation_journal_event,
        study,
        batch,
        *trials,
    ]
    include_progress = tamper != "target_pending"
    if include_progress:
        target_executable_id = prospective_ids[-1]
        if tamper == "wrong_progress_target":
            target_executable_id = prospective_ids[0]
        binding = ReplayExecutionBinding(
            obligation_ids=(obligation.identity,),
            portfolio_decision_id=portfolio_decision_id,
            replay_study_id=study_id,
            replay_executable_id=target_executable_id,
        )
        progress_payload = {
            "binding": binding.to_identity_payload(),
            "obligation_id": obligation.identity,
            "prior_status": "pending",
        }
        if tamper == "progress_payload":
            progress_payload["unexpected"] = True
        progress = IndexRecord(
            kind="historical-replay-obligation-progress",
            record_id="historical-replay-progress:"
            + canonical_digest(
                domain="historical-replay-obligation-progress",
                payload=progress_payload,
            ),
            subject=f"Mission:{mission_id}",
            status="in_progress",
            fingerprint=binding.identity,
            payload=progress_payload,
            event_stream=obligation_stream,
            event_sequence=4,
            authority_sequence=7,
            authority_event_id=f"{7:064x}",
            authority_offset=700,
        )
        progress_operation_id = "fixture-target-trial-registration"
        progress_operation = IndexRecord(
            kind="operation",
            record_id=progress_operation_id,
            subject=f"Executable:{prospective_ids[-1]}",
            status="success",
            fingerprint="fixture-target-trial-registration",
            payload={"event_kind": "trial_registered", "result": {}},
            authority_sequence=7,
            authority_event_id=f"{7:064x}",
            authority_offset=700,
        )
        progress_journal_event = IndexRecord(
            kind="journal-event",
            record_id=f"{7:064x}",
            subject=f"Executable:{prospective_ids[-1]}",
            status="trial_registered",
            fingerprint=f"{7:064x}",
            payload={"operation_id": progress_operation_id},
            event_stream="control",
            event_sequence=7,
            authority_sequence=7,
            authority_event_id=f"{7:064x}",
            authority_offset=700,
        )
        records.extend((progress, progress_operation, progress_journal_event))

    execution_order = list(prospective_ids[:prefix_length])
    if tamper == "execution_non_prefix" and prefix_length >= 2:
        execution_order[0], execution_order[1] = (
            execution_order[1],
            execution_order[0],
        )
    current_job_id = ""
    current_job_hash = ""
    budget_stream = f"batch-budget:{batch_spec.identity}"
    for ordinal, executable_id in enumerate(execution_order, start=1):
        job_hash = f"{100 + ordinal:064x}"
        job_id = f"job:{job_hash}"
        current_job_id = job_id
        current_job_hash = job_hash
        work_fingerprint = f"{200 + ordinal:064x}"
        declaration = IndexRecord(
            kind="job-declared",
            record_id=job_id,
            subject=f"Job:{job_id}",
            status="declared",
            fingerprint=job_hash,
            payload={
                "batch_id": batch_spec.identity,
                "mission_id": mission_id,
                "spec": {
                    "evidence_subject": {
                        "kind": "Executable",
                        "id": executable_id,
                    }
                },
                "study_id": study_id,
                "work_fingerprint": work_fingerprint,
            },
            event_stream=f"job-attempt:{work_fingerprint}",
            event_sequence=1,
            authority_sequence=20 + ordinal,
            authority_event_id=f"{20 + ordinal:064x}",
            authority_offset=(20 + ordinal) * 100,
        )
        reservation = IndexRecord(
            kind="batch-budget-reservation",
            record_id=f"{300 + ordinal:064x}",
            subject=f"Batch:{batch_spec.identity}",
            status="reserved",
            fingerprint=job_hash,
            payload={
                "compute_seconds": ordinal,
                "job_id": job_id,
                "wall_seconds": ordinal,
            },
            event_stream=budget_stream,
            event_sequence=ordinal,
            authority_sequence=20 + ordinal,
            authority_event_id=f"{20 + ordinal:064x}",
            authority_offset=(20 + ordinal) * 100,
        )
        records.extend((reservation, declaration))
        if ordinal == prefix_length:
            continue
        completion = IndexRecord(
            kind="job-completed",
            record_id=f"{400 + ordinal:064x}",
            subject=f"Job:{job_id}",
            status="success",
            fingerprint=job_hash,
            payload={"job_id": job_id},
            event_stream=declaration.event_stream,
            event_sequence=2,
            authority_sequence=30 + ordinal,
            authority_event_id=f"{30 + ordinal:064x}",
            authority_offset=(30 + ordinal) * 100,
        )
        decision = IndexRecord(
            kind="job-evidence-decision",
            record_id=f"decision:{500 + ordinal:064x}",
            subject=f"Job:{job_id}",
            status="continue_batch",
            fingerprint=job_hash,
            payload={"completion_record_id": completion.record_id},
            authority_sequence=40 + ordinal,
            authority_event_id=f"{40 + ordinal:064x}",
            authority_offset=(40 + ordinal) * 100,
        )
        if tamper != "prior_completion_missing" or ordinal != 1:
            records.append(completion)
        if tamper != "prior_decision_missing" or ordinal != 1:
            records.append(decision)

    with LocalIndex(index_path) as index:
        index.rebuild(records)

    subject_executable_id = prospective_ids[prefix_length - 1]
    execution = RunningJobExecution(
        job_id=current_job_id,
        job_hash=current_job_hash,
        start_record_id="3" * 64,
        job_permit_id="4" * 64,
    )
    job_binding = {
        "batch_id": batch_spec.identity,
        "execution": execution.payload(),
        "mission_id": mission_id,
        "spec": {
            "evidence_subject": {
                "kind": "Executable",
                "id": subject_executable_id,
            }
        },
        "study_id": study_id,
    }
    control = {
        "scientific": {
            "active_batch": {
                "hash": batch_digest,
                "id": batch_spec.identity,
                "status": "open",
            },
            "active_job": {
                "hash": execution.job_hash,
                "id": execution.job_id,
                "start_record_id": execution.start_record_id,
                "status": "running",
            },
            "active_mission": mission_id,
            "active_study": study_id,
        }
    }
    return SimpleNamespace(
        batch_id=batch_spec.identity,
        binding=job_binding,
        control=control,
        execution=execution,
        family=family,
        index_path=index_path,
        prospective_ids=prospective_ids,
        study_id=study_id,
        subject_executable_id=subject_executable_id,
    )


def _verified_replay_context(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixture: SimpleNamespace,
) -> RunningJobExecutionContext:
    class FakeAuthority:
        def __init__(self, repository_root: Path) -> None:
            self.foundation_root = repository_root

        def verify_running_job_execution(self, actual, **_kwargs):
            assert actual == fixture.execution
            return fixture.binding

        @contextmanager
        def open_stable_index(self):
            with LocalIndex(fixture.index_path) as index:
                yield fixture.control, index.read_only()

        def verify_reproducible_cache_producer(self, *_args, **_kwargs):
            raise AssertionError("unused")

    monkeypatch.setattr(context_module, "RunningJobAuthority", FakeAuthority)
    context = RunningJobExecutionContext(root)
    context.verify_running_job_execution(fixture.execution)
    return context


def test_all_prospective_study_runners_use_only_the_read_only_context() -> None:
    expected_runner_count = 0
    runner_count = 0
    environment_count = 0
    recertification_stable_index_access_count = 0
    violations: list[str] = []
    for path in (
        path
        for path in _tracked_research_paths()
        if path.name.endswith("_study.py")
    ):
        # These modules are byte-frozen evidence history, never prospective
        # engines.  Migrating them would destroy exact reconstruction.  Their
        # immutable hashes and quarantine are enforced independently by
        # test_implementation_identity.py.
        if path.name in HISTORICAL_RESEARCH_FILES:
            continue
        tree = ast.parse(path.read_text(encoding="ascii"), filename=str(path))
        has_context_constructor = False
        has_running_execution_import = False
        has_context_import = False
        is_runner = False
        context_variables: set[str] = set()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "RunningJobExecutionContext"
            ):
                context_variables.update(
                    target.id
                    for target in node.targets
                    if isinstance(target, ast.Name)
                )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for argument in (
                    *node.args.posonlyargs,
                    *node.args.args,
                    *node.args.kwonlyargs,
                ):
                    if (
                        isinstance(argument.annotation, ast.Name)
                        and argument.annotation.id == "RunningJobExecution"
                    ):
                        is_runner = True
                    if (
                        isinstance(argument.annotation, ast.Name)
                        and argument.annotation.id
                        == "RunningJobExecutionContext"
                    ):
                        context_variables.add(argument.arg)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported = {alias.name for alias in node.names}
                if node.module == "axiom_rift.operations.writer" and imported & {
                    "RunningJobExecution",
                    "StateWriter",
                }:
                    violations.append(f"{path.name}:{node.lineno}:writer_import")
                if node.module == "axiom_rift.operations" and "writer" in imported:
                    violations.append(
                        f"{path.name}:{node.lineno}:writer_module_import"
                    )
                if (
                    node.module == "axiom_rift.operations.running_job"
                    and "RunningJobExecution" in imported
                ):
                    has_running_execution_import = True
                if (
                    node.module
                    == "axiom_rift.operations.running_job_context"
                    and "RunningJobExecutionContext" in imported
                ):
                    has_context_import = True
            elif isinstance(node, ast.Import):
                if any(
                    alias.name == "axiom_rift.operations.writer"
                    for alias in node.names
                ):
                    violations.append(
                        f"{path.name}:{node.lineno}:writer_module_import"
                    )
            elif isinstance(node, ast.Name) and node.id in {
                "StateWriter",
                "writer_module",
            }:
                violations.append(
                    f"{path.name}:{node.lineno}:forbidden_name:{node.id}"
                )
            elif (
                isinstance(node, ast.Attribute)
                and node.attr == "_open_authoritative_index"
            ):
                violations.append(
                    f"{path.name}:{node.lineno}:private_index_access"
                )
            elif (
                isinstance(node, ast.Attribute)
                and node.attr == "open_stable_index"
            ):
                if path.name == "us500_recertification_study.py":
                    recertification_stable_index_access_count += 1
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in context_variables
                and node.attr
                not in {
                    "evidence",
                    "prior_global_multiplicity_floor",
                    "project_bound_fixed_hold_family_exposure",
                    "project_bound_fixed_hold_replay_context",
                    "project_bound_source_state",
                    "verify_reproducible_cache_producer",
                    "verify_running_job_execution",
                }
            ):
                violations.append(
                    f"{path.name}:{node.lineno}:context_capability:{node.attr}"
                )
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "RunningJobExecutionContext"
            ):
                has_context_constructor = True
            elif isinstance(node, ast.Dict):
                pairs = _constant_dict_pairs(node)
                if pairs.get("schema") == "scientific_engine_environment.v1":
                    environment_count += 1
                    keys = {
                        key.value
                        for key in node.keys
                        if isinstance(key, ast.Constant)
                        and isinstance(key.value, str)
                    }
                    if "writer_implementation_sha256" in keys:
                        violations.append(
                            f"{path.name}:{node.lineno}:writer_hash"
                        )
                    if (
                        "running_job_context_implementation_sha256"
                        not in keys
                    ):
                        violations.append(
                            f"{path.name}:{node.lineno}:context_hash_missing"
                        )
        if is_runner:
            expected_runner_count += 1
        if has_context_constructor:
            runner_count += 1
            if not has_running_execution_import:
                violations.append(f"{path.name}:running_execution_import_missing")
            if not has_context_import:
                violations.append(f"{path.name}:context_import_missing")

        if is_runner and not has_context_constructor:
            violations.append(f"{path.name}:context_constructor_missing")

    assert expected_runner_count > 0
    assert runner_count == expected_runner_count
    assert environment_count > 0
    assert recertification_stable_index_access_count == 0
    assert violations == []


def test_all_nonhistorical_research_modules_are_writer_free() -> None:
    """Prospective engines cannot reach the mutation-capable state writer."""

    audited: set[str] = set()
    violations: list[str] = []
    for path in _tracked_research_paths():
        if path.name in HISTORICAL_RESEARCH_FILES:
            continue
        audited.add(path.name)
        tree = ast.parse(path.read_text(encoding="ascii"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module == "axiom_rift.operations.writer":
                    violations.append(f"{path.name}:{node.lineno}:writer_import")
                if node.module == "axiom_rift.operations" and any(
                    alias.name == "writer" for alias in node.names
                ):
                    violations.append(
                        f"{path.name}:{node.lineno}:writer_module_import"
                    )
            elif isinstance(node, ast.Import) and any(
                alias.name == "axiom_rift.operations.writer"
                for alias in node.names
            ):
                violations.append(
                    f"{path.name}:{node.lineno}:writer_module_import"
                )
            elif isinstance(node, ast.Name) and node.id == "StateWriter":
                violations.append(
                    f"{path.name}:{node.lineno}:state_writer_reference"
                )

    assert "analog_state_replay.py" in audited
    assert "gap_recovery_diagnostic.py" not in audited
    assert violations == []


def test_analog_replay_import_cannot_reach_state_writer() -> None:
    environment = dict(os.environ)
    prior = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        str(SOURCE_ROOT)
        if not prior
        else os.pathsep.join((str(SOURCE_ROOT), prior))
    )
    source = """
import json
import sys
import axiom_rift.research.analog_state_replay as replay
print(json.dumps({
    "context": replay.RunningJobExecutionContext.__module__,
    "state_writer_attribute": hasattr(replay, "StateWriter"),
    "writer_loaded": "axiom_rift.operations.writer" in sys.modules,
}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", source],
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(completed.stdout) == {
        "context": "axiom_rift.operations.running_job_context",
        "state_writer_attribute": False,
        "writer_loaded": False,
    }


def test_running_job_context_exposes_no_state_mutation_api(
    tmp_path: Path,
) -> None:
    public_callables = {
        name
        for name in dir(RunningJobExecutionContext)
        if not name.startswith("_")
        and callable(getattr(RunningJobExecutionContext, name))
    }
    assert public_callables == {
        "project_bound_fixed_hold_family_exposure",
        "project_bound_fixed_hold_replay_context",
        "project_bound_source_state",
        "verify_reproducible_cache_producer",
        "verify_running_job_execution",
    }
    assert set(RunningJobExecutionContext.__slots__) == {
        "__authority",
        "__bound_job",
        "__evidence",
        "__prior_global_multiplicity_floor",
    }
    _write_test_foundation(tmp_path)
    context = RunningJobExecutionContext(tmp_path)
    assert context.prior_global_multiplicity_floor == 7
    for forbidden in (
        "_authority",
        "foundation_root",
        "index_path",
        "open_stable_index",
        "read_control",
        "root",
        "verified_path",
    ):
        assert not hasattr(context, forbidden)
    with pytest.raises(AttributeError, match="internals are not exposed"):
        getattr(context, "_RunningJobExecutionContext__authority")
    evidence = context.evidence
    assert not isinstance(evidence, EvidenceStore)
    evidence_callables = {
        name
        for name in dir(evidence)
        if not name.startswith("_") and callable(getattr(evidence, name))
    }
    assert evidence_callables == {"finalize", "read_verified"}
    for forbidden in (
        "_root",
        "_target",
        "verified_path",
        "verify",
        "verify_manifest",
    ):
        assert not hasattr(evidence, forbidden)
    with pytest.raises(AttributeError, match="not exposed"):
        getattr(evidence, "_RunningJobEvidenceFacade__store")
    artifact = evidence.finalize(b"facade evidence")
    assert evidence.read_verified(artifact.sha256) == b"facade evidence"


def test_context_projects_only_the_verified_execution_family(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_test_foundation(tmp_path, prior_floor=7)
    index_path = tmp_path / "projection.sqlite"
    study_id = "STU-TEMP"
    study_hash = "c" * 64
    study = IndexRecord(
        kind="study-open",
        record_id=study_id,
        subject=f"Study:{study_id}",
        status="open",
        fingerprint=study_hash,
        payload={},
    )
    batch_spec = {
        "schema": "batch_spec.v1",
        "study_hash": study_hash,
    }
    batch_digest = canonical_digest(
        domain="batch-spec",
        payload=batch_spec,
    )
    batch_id = f"batch:{batch_digest}"
    family_ids = (
        "executable:" + "a" * 64,
        "executable:" + "b" * 64,
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
    prior = IndexRecord(
        kind="trial",
        record_id="executable:" + "d" * 64,
        subject="Batch:prior",
        status="evaluated",
        fingerprint="d" * 64,
        payload={"study_id": "STU-PRIOR"},
        authority_sequence=1,
        authority_event_id="1" * 64,
        authority_offset=1,
    )
    family = tuple(
        IndexRecord(
            kind="trial",
            record_id=identity,
            subject=f"Batch:{batch_id}",
            status="evaluated",
            fingerprint=identity.removeprefix("executable:"),
            payload={"study_id": study_id},
            event_stream=f"batch-trials:{batch_id}",
            event_sequence=ordinal,
            authority_sequence=9 + ordinal,
            authority_event_id=f"{9 + ordinal:064x}",
            authority_offset=9 + ordinal,
        )
        for ordinal, identity in enumerate(family_ids, start=1)
    )
    with LocalIndex(index_path) as index:
        index.rebuild((study, batch, prior, *family))

    execution = RunningJobExecution(
        job_id="job:" + "1" * 64,
        job_hash="2" * 64,
        start_record_id="3" * 64,
        job_permit_id="4" * 64,
    )
    binding = {
        "batch_id": batch_id,
        "execution": execution.payload(),
        "mission_id": "MIS-TEMP",
        "spec": {
            "evidence_subject": {
                "kind": "Executable",
                "id": family_ids[0],
            }
        },
        "study_id": study_id,
    }

    class FakeAuthority:
        def __init__(self, root: Path) -> None:
            self.foundation_root = root

        def verify_running_job_execution(self, actual, **_kwargs):
            assert actual == execution
            return binding

        @contextmanager
        def open_stable_index(self):
            control = {
                "scientific": {
                    "active_job": {
                        "hash": execution.job_hash,
                        "id": execution.job_id,
                        "start_record_id": execution.start_record_id,
                        "status": "running",
                    }
                }
            }
            with LocalIndex(index_path) as index:
                yield control, index.read_only()

        def verify_reproducible_cache_producer(self, *_args, **_kwargs):
            raise AssertionError("unused")

    monkeypatch.setattr(context_module, "RunningJobAuthority", FakeAuthority)
    context = RunningJobExecutionContext(tmp_path)
    context.verify_running_job_execution(execution)
    projection = context.project_bound_fixed_hold_family_exposure(
        study_id=study_id,
        batch_id=batch_id,
        subject_executable_id=family_ids[0],
        expected_family_size=2,
        parameter_name=None,
    )
    assert projection.family_executable_ids == family_ids
    assert projection.prior_global_exposure_count == 8
    for overrides in (
        {"study_id": "STU-OTHER"},
        {"batch_id": "batch:other"},
        {"subject_executable_id": family_ids[1]},
    ):
        request = {
            "study_id": study_id,
            "batch_id": batch_id,
            "subject_executable_id": family_ids[0],
            "expected_family_size": 2,
            "parameter_name": None,
            **overrides,
        }
        with pytest.raises(
            RunningJobAuthorityError,
            match="differs from the verified Job",
        ):
            context.project_bound_fixed_hold_family_exposure(**request)


@pytest.mark.parametrize("prefix_length", (1, 2, 3))
def test_fixed_hold_replay_non_target_jobs_require_full_family_and_execution_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prefix_length: int,
) -> None:
    fixture = _build_fixed_hold_replay_projection(
        tmp_path,
        prefix_length=prefix_length,
    )
    context = _verified_replay_context(tmp_path, monkeypatch, fixture)

    projection = context.project_bound_fixed_hold_replay_context(
        study_id=fixture.study_id,
        batch_id=fixture.batch_id,
        subject_executable_id=fixture.subject_executable_id,
        expected_family_size=4,
        parameter_name=None,
    )

    historical_family = tuple(
        member.historical_reference_executable_id
        for member in fixture.family.members
    )
    assert projection.exposure.family_executable_ids == fixture.prospective_ids
    assert projection.registered_member_bindings == tuple(
        zip(
            fixture.prospective_ids,
            historical_family,
            strict=True,
        )
    )
    assert projection.execution_prefix_executable_ids == (
        fixture.prospective_ids[:prefix_length]
    )
    assert projection.completed_member_executable_ids == (
        fixture.prospective_ids[: prefix_length - 1]
    )
    assert projection.target_prospective_executable_id == (
        fixture.prospective_ids[-1]
    )


def test_fixed_hold_replay_target_job_requires_exact_in_progress_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _build_fixed_hold_replay_projection(
        tmp_path,
        prefix_length=4,
    )
    context = _verified_replay_context(tmp_path, monkeypatch, fixture)

    projection = context.project_bound_fixed_hold_replay_context(
        study_id=fixture.study_id,
        batch_id=fixture.batch_id,
        subject_executable_id=fixture.subject_executable_id,
        expected_family_size=4,
        parameter_name=None,
    )

    assert projection.exposure.family_executable_ids == fixture.prospective_ids
    assert projection.target_prospective_executable_id == (
        fixture.prospective_ids[-1]
    )
    assert projection.registered_member_bindings[-1] == (
        fixture.prospective_ids[-1],
        fixture.family.target_historical_executable_id,
    )
    assert projection.execution_prefix_executable_ids == fixture.prospective_ids
    assert projection.completed_member_executable_ids == (
        fixture.prospective_ids[:-1]
    )


@pytest.mark.parametrize(
    ("prefix_length", "tamper", "message"),
    (
        (2, "non_prefix", "prospective family differs"),
        (2, "invalidation_result", "same-event Writer authority"),
        (3, "family_cross_event", "same-event Writer authority"),
        (1, "target_pending", "fully registered family lacks progress"),
        (4, "wrong_progress_target", "execution binding differs"),
        (4, "progress_payload", "execution binding differs"),
        (2, "execution_non_prefix", "execution declarations are not an exact prefix"),
        (2, "prior_completion_missing", "completed-member prefix"),
        (2, "prior_decision_missing", "completed-member prefix"),
    ),
)
def test_fixed_hold_replay_context_rejects_authority_and_prefix_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prefix_length: int,
    tamper: str,
    message: str,
) -> None:
    fixture = _build_fixed_hold_replay_projection(
        tmp_path,
        prefix_length=prefix_length,
        tamper=tamper,
    )
    context = _verified_replay_context(tmp_path, monkeypatch, fixture)

    with pytest.raises(RunningJobAuthorityError, match=message):
        context.project_bound_fixed_hold_replay_context(
            study_id=fixture.study_id,
            batch_id=fixture.batch_id,
            subject_executable_id=fixture.subject_executable_id,
            expected_family_size=4,
            parameter_name=None,
        )


def test_running_job_authority_rejects_bool_counters() -> None:
    for field, event in (
        ("sequence", {"sequence": True, "index_record_count": 1}),
        ("record_count", {"sequence": 1, "index_record_count": True}),
    ):
        with pytest.raises(RunningJobAuthorityIntegrityError):
            RunningJobAuthority._assemble(event)


def test_authority_manifest_rejects_noncanonical_and_casefold_aliases(
    tmp_path: Path,
) -> None:
    authority = RunningJobAuthority(tmp_path, foundation_root=tmp_path)
    for relative in ("../outside.md", "nested/../outside.md", "nested\\file.md"):
        with pytest.raises(
            RunningJobAuthorityIntegrityError,
            match="canonical and relative",
        ):
            authority._authority_manifest_digest(
                {
                    "operating_direction": relative,
                    "contracts": [],
                    "foundation_inputs": [],
                }
            )

    with pytest.raises(
        RunningJobAuthorityIntegrityError,
        match="portable-unique",
    ):
        authority._authority_manifest_digest(
            {
                "operating_direction": "Direction.md",
                "contracts": ["direction.md"],
                "foundation_inputs": [],
            }
        )


def test_authority_manifest_rejects_hard_link_and_symbolic_link_aliases(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.md"
    target.write_bytes(b"authority")
    hard_link = tmp_path / "hard-link.md"
    os.link(target, hard_link)
    authority = RunningJobAuthority(tmp_path, foundation_root=tmp_path)

    with pytest.raises(
        RunningJobAuthorityIntegrityError,
        match="absent or unsafe",
    ):
        authority._authority_manifest_digest(
            {
                "operating_direction": "hard-link.md",
                "contracts": [],
                "foundation_inputs": [],
            }
        )

    hard_link.unlink()
    symbolic_link = tmp_path / "symbolic-link.md"
    try:
        symbolic_link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symbolic links unavailable: {exc}")
    with pytest.raises(
        RunningJobAuthorityIntegrityError,
        match="absent or unsafe",
    ):
        authority._authority_manifest_digest(
            {
                "operating_direction": "symbolic-link.md",
                "contracts": [],
                "foundation_inputs": [],
            }
        )


def test_running_job_repair_trace_rejects_bool_artifact_count() -> None:
    job_id = "job:" + "1" * 64
    old_identity = "2" * 64
    new_identity = "3" * 64
    plan_hash = "4" * 64
    result_hash = "5" * 64
    inventory_hash = "6" * 64
    measurement_hash = "7" * 64
    claims = ["callable"]
    repair_payload = {
        "effective_implementation_identity": new_identity,
        "job_id": job_id,
        "previous_effective_implementation_identity": old_identity,
        "repair_id": "repair:" + "8" * 64,
        "semantic_equivalence_validation": {
            "binding": {
                "claims": claims,
                "measurement_artifact_hashes": [measurement_hash],
                "new_implementation_identity": new_identity,
                "old_implementation_identity": old_identity,
                "repair_id": "repair:" + "8" * 64,
                "result_manifest_hash": result_hash,
                "surface_inventory_hash": inventory_hash,
                "validation_plan_hash": plan_hash,
                "validator_id": "validator:" + "9" * 64,
            },
            "claims": claims,
            "facts": {
                "covered_surface_ids": claims,
                "new_implementation_identity": new_identity,
                "old_implementation_identity": old_identity,
                "result_manifest_hash": result_hash,
                "surface_inventory_hash": inventory_hash,
                "validation_plan_hash": plan_hash,
            },
            "measurement_artifact_hashes": [measurement_hash],
            "registry_trace": {
                "declared_artifact_count": True,
                "opened_artifact_count": True,
                "validator_id": "validator:" + "9" * 64,
            },
            "schema": (
                "implementation_repair_semantic_equivalence_validation.v1"
            ),
            "verdict": "passed",
        },
    }
    repair_record = SimpleNamespace(
        kind="repair-close",
        payload=repair_payload,
        record_id="a" * 64,
        status="repaired",
        subject=f"Job:{job_id}",
    )
    declaration = SimpleNamespace(
        payload={
            "spec": {
                "evidence_subject": {
                    "id": "executable:" + "b" * 64,
                    "kind": "Executable",
                }
            }
        }
    )
    trial = SimpleNamespace(payload={"engineering_fixture": False})

    class FakeIndex:
        def event_head(self, stream: str) -> object:
            assert stream == f"job-repair:{job_id}"
            return SimpleNamespace(
                record_id=repair_record.record_id,
                record_kind="repair-close",
            )

        def get(self, kind: str, record_id: str) -> object:
            if kind == "repair-close":
                return repair_record
            if kind == "job-declared":
                return declaration
            if kind == "trial":
                return trial
            raise AssertionError((kind, record_id))

    with pytest.raises(
        RunningJobAuthorityIntegrityError,
        match="complete registered semantic-equivalence authority",
    ):
        effective_running_job_implementation(
            FakeIndex(),  # type: ignore[arg-type]
            job_id=job_id,
            declared_implementation_identity=old_identity,
        )


def test_context_digest_binds_only_its_exact_project_local_closure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = running_job_execution_context_dependency_paths()
    assert paths == tuple(sorted(set(paths), key=lambda path: path.as_posix()))
    assert CONTEXT_PATH in paths
    assert RUNNING_JOB_PATH in paths
    assert WRITER_PATH not in paths
    assert all(path.is_file() and path.is_relative_to(SOURCE_ROOT) for path in paths)

    manifest = running_job_execution_context_dependency_manifest()
    assert manifest["schema"] == (
        "running_job_execution_context_dependency_closure.v1"
    )
    assert manifest["dependencies"] == [
        {
            "path": path.relative_to(SOURCE_ROOT).as_posix(),
            "sha256": sha256(path.read_bytes()).hexdigest(),
        }
        for path in paths
    ]
    running_job_execution_context_implementation_sha256.cache_clear()
    baseline = running_job_execution_context_implementation_sha256()
    assert baseline == canonical_digest(
        domain="running-job-execution-context-dependency-closure",
        payload=manifest,
    )

    original_read_bytes = Path.read_bytes

    def perturb_context_dependency(path: Path) -> bytes:
        content = original_read_bytes(path)
        if path.resolve() == RUNNING_JOB_PATH:
            return content + b"\n# context dependency perturbation"
        return content

    monkeypatch.setattr(Path, "read_bytes", perturb_context_dependency)
    running_job_execution_context_implementation_sha256.cache_clear()
    assert running_job_execution_context_implementation_sha256() != baseline

    def perturb_unrelated_writer(path: Path) -> bytes:
        content = original_read_bytes(path)
        if path.resolve() == WRITER_PATH:
            return content + b"\n# unrelated writer perturbation"
        return content

    monkeypatch.setattr(Path, "read_bytes", perturb_unrelated_writer)
    running_job_execution_context_implementation_sha256.cache_clear()
    assert running_job_execution_context_implementation_sha256() == baseline
