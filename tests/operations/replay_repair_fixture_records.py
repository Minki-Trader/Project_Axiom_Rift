from __future__ import annotations

from typing import Any

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.repair_semantic_equivalence import (
    FIXED_HOLD_AUTHORITY_CORRECTION_CASE_IDS,
    FIXED_HOLD_AUTHORITY_CORRECTION_FACTS_SCHEMA,
    FIXED_HOLD_AUTHORITY_CORRECTION_METHOD,
    FIXED_HOLD_AUTHORITY_CORRECTION_PROTOCOL,
    SEMANTIC_EQUIVALENCE_BINDING_SCHEMA,
)
from axiom_rift.operations.scientific_multiplicity_authority import (
    build_multiplicity_batch_binding,
)
from axiom_rift.research.portfolio import (
    BatchSpec,
    ConcurrentFamilyEvaluationMode,
    ConcurrentFamilyManifest,
)
from axiom_rift.storage.index import IndexRecord


STUDY_ID = "STU-REPAIR-ADMISSION"
MISSION_ID = "MIS-REPAIR-ADMISSION"
OBLIGATION_ID = "historical-replay-obligation:" + "a" * 64
JOB_ID = "job:" + "c" * 64
OLD_IMPLEMENTATION = "1" * 64
NEW_IMPLEMENTATION = "2" * 64
THIRD_IMPLEMENTATION = "3" * 64
REPRODUCTION_HASH = "0123456789abcdef" * 4
VERIFICATION_HASH = "fedcba9876543210" * 4
ATTEMPT_PROOF_HASH = "a" * 64
START_RECORD_ID = "b" * 64
JOB_PERMIT_ID = "c" * 64
ENGINE_ENTRY_RECORD_ID = "d" * 64
VALIDATION_PLAN_HASH = "4" * 64
VALIDATOR_ID = "validator:" + "5" * 64
MATERIAL_IDENTITY = "material:" + "6" * 64
SCIENTIFIC_CLAIMS = ["C01-fixed-hold-selection"]
SCIENTIFIC_MODES = [
    "causal_contrast",
    "cost_and_execution",
    "sensitivity_or_stress",
    "temporal_stability",
]


def _manifest(label: str) -> dict[str, Any]:
    return {"label": label, "schema": "fixture_executable.v1"}


def _executable_id(manifest: dict[str, Any]) -> str:
    return "executable:" + canonical_digest(
        domain="executable",
        payload=manifest,
    )


MANIFESTS = (_manifest("producer-first"), _manifest("control-second"))
REGISTERED = tuple(_executable_id(manifest) for manifest in MANIFESTS)
CONCURRENT_FAMILY = ConcurrentFamilyManifest(
    evaluation_mode=ConcurrentFamilyEvaluationMode.VECTORIZED,
    executable_ids=tuple(sorted(REGISTERED)),
)
BATCH_SPEC = BatchSpec(
    batch_id="BAT-REPAIR-ADMISSION",
    study_id=STUDY_ID,
    study_hash="7" * 64,
    display_name="repair admission fixture",
    max_trials=len(REGISTERED),
    max_compute_seconds=10,
    max_wall_seconds=20,
    stop_rule="complete the exact family",
    concurrent_family=CONCURRENT_FAMILY,
    acceptance_profile={"candidate_authority": "none"},
    adaptive_basis={
        "causal_complexity": "bounded",
        "compute_cost": "bounded",
        "expected_information_value": "bounded",
        "portfolio_opportunity_cost": "bounded",
        "surface_curvature": "fixed",
        "uncertainty": "registered",
    },
)
BATCH_ID = BATCH_SPEC.identity


def _scientific_binding() -> dict[str, Any]:
    return {
        "evidence_depth": "discovery",
        "evidence_modes": list(SCIENTIFIC_MODES),
        "planned_claims": list(SCIENTIFIC_CLAIMS),
        "validation_plan_hash": VALIDATION_PLAN_HASH,
        "validator_id": VALIDATOR_ID,
    }


def _request(implementation_identity: str) -> dict[str, Any]:
    return {
        "callable_identity": "fixture.replay:run",
        "executable_manifests": [dict(manifest) for manifest in MANIFESTS],
        "implementation_identity": implementation_identity,
        "mission_id": MISSION_ID,
        "protocol_id": "fixture.concurrent.replay.v1",
        "replacement_for_preflight_id": None,
        "replay_obligation_ids": [OBLIGATION_ID],
        "schema": "replay_job_implementation_preflight_request.v1",
        "scientific_bindings": [
            _scientific_binding(),
            _scientific_binding(),
        ],
    }


def _event_id(sequence: int) -> str:
    return f"{sequence:064x}"


def _repair_open_record(
    *,
    episode: int,
    predecessor_close_id: str | None,
    authority_sequence: int,
    root_cause: str,
) -> IndexRecord:
    failure_manifest = {
        "failure_kind": "engineering",
        "interrupted_action": "fixture.replay:run",
        "minimum_reproduction_evidence": [REPRODUCTION_HASH],
        "root_cause": root_cause,
    }
    cause_hash = canonical_digest(
        domain="repair-cause",
        payload=failure_manifest,
    )
    repair_id = "repair:" + canonical_digest(
        domain="repair",
        payload={
            "cause_hash": cause_hash,
            "episode": episode,
            "job_id": JOB_ID,
            "predecessor_repair_close_record_id": predecessor_close_id,
        },
    )
    return IndexRecord(
        kind="repair-open",
        record_id=repair_id,
        subject=f"Job:{JOB_ID}",
        status="open",
        fingerprint=cause_hash,
        payload={
            **failure_manifest,
            "episode": episode,
            "predecessor_repair_close_record_id": predecessor_close_id,
            "resume_action": "continue_batch",
            "scientific_trial_delta": 0,
        },
        authority_sequence=authority_sequence,
        authority_event_id=_event_id(authority_sequence),
        authority_offset=0,
    )


def _content_record(
    *,
    kind: str,
    prefix: str,
    domain: str,
    subject: str,
    status: str,
    payload: dict[str, Any],
    authority_sequence: int,
    event_stream: str | None = None,
    event_sequence: int | None = None,
) -> IndexRecord:
    fingerprint = canonical_digest(domain=domain, payload=payload)
    return IndexRecord(
        kind=kind,
        record_id=prefix + fingerprint,
        subject=subject,
        status=status,
        fingerprint=fingerprint,
        payload=payload,
        event_stream=event_stream,
        event_sequence=event_sequence,
        authority_sequence=authority_sequence,
        authority_event_id=_event_id(authority_sequence),
        authority_offset=0,
    )


def _repair_semantic_validation(
    executable_id: str,
    *,
    repair_id: str,
    old_implementation: str = OLD_IMPLEMENTATION,
    new_implementation: str = NEW_IMPLEMENTATION,
    old_closure: str = "8" * 64,
    new_closure: str = "9" * 64,
    old_source: str = "a" * 64,
    new_source: str = "b" * 64,
    unchanged: str = "c" * 64,
) -> dict[str, Any]:
    result_hash = "d" * 64
    plan_hash = "e" * 64
    measurement_hash = "f" * 64
    inventory_hash = "0" * 64
    relative_path = "src/fixture.py"
    source_inventory_hash = canonical_digest(
        domain="implementation-repair-source-path-inventory",
        payload={"relative_paths": [relative_path]},
    )
    old_artifacts = sorted((old_closure, old_source, unchanged))
    new_artifacts = sorted((new_closure, new_source, unchanged))
    declared = sorted(
        {
            plan_hash,
            result_hash,
            old_implementation,
            new_implementation,
            measurement_hash,
            *old_artifacts,
            *new_artifacts,
        }
    )
    changed_pair = {
        "new_artifact_hash": new_source,
        "old_artifact_hash": old_source,
        "relative_path": relative_path,
    }
    claims = ["fixture_authority_projection"]
    binding = {
        "changed_source_pair_bindings": [changed_pair],
        "claims": claims,
        "declared_artifact_hashes": declared,
        "executable_id": executable_id,
        "measurement_artifact_hashes": [measurement_hash],
        "new_implementation_artifact_hashes": new_artifacts,
        "new_implementation_identity": new_implementation,
        "new_source_closure_hash": new_closure,
        "old_implementation_artifact_hashes": old_artifacts,
        "old_implementation_identity": old_implementation,
        "old_source_closure_hash": old_closure,
        "repair_id": repair_id,
        "result_manifest_hash": result_hash,
        "schema": SEMANTIC_EQUIVALENCE_BINDING_SCHEMA,
        "source_path_inventory_hash": source_inventory_hash,
        "surface_inventory_hash": inventory_hash,
        "validation_plan_hash": plan_hash,
        "validator_id": "validator:" + "1" * 64,
    }
    facts = {
        "added_artifact_hashes": sorted((new_closure, new_source)),
        "artifact_equivalence_method": FIXED_HOLD_AUTHORITY_CORRECTION_METHOD,
        "authority_deltas": {
            "candidate": 0,
            "holdout_reveal": 0,
            "scientific_claim": 0,
            "scientific_satisfaction": 0,
            "scientific_trial": 0,
        },
        "changed_source_pair_results": [
            {
                "changed_symbols": ["fixture_symbol"],
                **changed_pair,
            }
        ],
        "conformance_case_ids": list(
            FIXED_HOLD_AUTHORITY_CORRECTION_CASE_IDS
        ),
        "covered_surface_ids": claims,
        "new_implementation_artifact_hashes": new_artifacts,
        "new_implementation_identity": new_implementation,
        "new_source_closure_hash": new_closure,
        "old_implementation_artifact_hashes": old_artifacts,
        "old_implementation_identity": old_implementation,
        "old_source_closure_hash": old_closure,
        "pairing_status": "passed",
        "removed_artifact_hashes": sorted((old_closure, old_source)),
        "repair_id": repair_id,
        "result_manifest_hash": result_hash,
        "schema": FIXED_HOLD_AUTHORITY_CORRECTION_FACTS_SCHEMA,
        "source_path_bindings": [{"changed": True, **changed_pair}],
        "source_path_inventory_hash": source_inventory_hash,
        "surface_inventory_hash": inventory_hash,
        "unchanged_artifact_hashes": [unchanged],
        "validation_plan_hash": plan_hash,
        "validation_protocol": FIXED_HOLD_AUTHORITY_CORRECTION_PROTOCOL,
        "validator_id": binding["validator_id"],
    }
    return {
        "binding": binding,
        "claims": claims,
        "facts": facts,
        "measurement_artifact_hashes": [measurement_hash],
        "registry_trace": {
            "declared_artifact_count": len(declared),
            "opened_artifact_count": len(declared),
            "validator_id": binding["validator_id"],
        },
        "schema": "implementation_repair_semantic_equivalence_validation.v1",
        "verdict": "passed",
    }


def _repair_attempt_and_close_records(
    *,
    opened: IndexRecord,
    previous_implementation: str,
    next_implementation: str,
    semantic_validation: dict[str, Any],
    event_sequence: int,
    authority_sequence: int,
    attempt_proof_hash: str,
) -> tuple[IndexRecord, IndexRecord]:
    binding = semantic_validation["binding"]
    new_evidence = sorted(
        {
            next_implementation,
            binding["validation_plan_hash"],
            binding["result_manifest_hash"],
            *binding["measurement_artifact_hashes"],
            *binding["new_implementation_artifact_hashes"],
        }
    )
    attempt_identity_payload = {
        "attempt_proof_hash": attempt_proof_hash,
        "cause_hash": opened.fingerprint,
        "changed_dimension": "implementation",
        "explanation": "repair the implementation without changing science",
        "failure_observation": None,
        "implementation_proof_hash": binding["result_manifest_hash"],
        "job_hash": JOB_ID.removeprefix("job:"),
        "job_id": JOB_ID,
        "new_basis_hash": next_implementation,
        "new_evidence_hashes": new_evidence,
        "outcome": "repaired",
        "previous_basis_hash": opened.fingerprint,
        "prior_attempt_record_id": None,
        "repair_id": opened.record_id,
        "reproduction_evidence_hashes": [REPRODUCTION_HASH],
        "resume_action": "continue_batch",
        "schema": "running_job_repair_attempt.v1",
        "scientific_semantics_changed": False,
        "semantic_equivalence_validation": semantic_validation,
        "verification_evidence_hashes": [VERIFICATION_HASH],
    }
    attempt_id = canonical_digest(
        domain="repair-attempt",
        payload=attempt_identity_payload,
    )
    attempt = IndexRecord(
        kind="repair-attempt",
        record_id=attempt_id,
        subject=f"Repair:{opened.record_id}",
        status="repaired",
        fingerprint=attempt_proof_hash,
        payload={
            **attempt_identity_payload,
            "scientific_failure_delta": 0,
            "scientific_trial_delta": 0,
        },
        event_stream=f"repair-attempt:{opened.record_id}",
        event_sequence=1,
        authority_sequence=authority_sequence,
        authority_event_id=_event_id(authority_sequence),
        authority_offset=0,
    )
    close_identity_payload = {
        "proof": attempt_proof_hash,
        "repair_id": opened.record_id,
        "semantic_equivalence_validation": semantic_validation,
    }
    close_id = canonical_digest(
        domain="repair-close",
        payload=close_identity_payload,
    )
    close = IndexRecord(
        kind="repair-close",
        record_id=close_id,
        subject=f"Job:{JOB_ID}",
        status="repaired",
        fingerprint=attempt_proof_hash,
        payload={
            "attempt_record_id": attempt.record_id,
            "changed_cause_proof_hash": attempt_proof_hash,
            "changed_dimension": "implementation",
            "effective_implementation_identity": next_implementation,
            "implementation_changed": True,
            "job_id": JOB_ID,
            "previous_effective_implementation_identity": (
                previous_implementation
            ),
            "prior_attempt_record_id": None,
            "repair_id": opened.record_id,
            "resume_action": "continue_batch",
            "scientific_failure_delta": 0,
            "scientific_trial_delta": 0,
            "semantic_equivalence_validation": semantic_validation,
            "verification_evidence_hashes": [VERIFICATION_HASH],
        },
        event_stream=f"job-repair:{JOB_ID}",
        event_sequence=event_sequence,
        authority_sequence=authority_sequence,
        authority_event_id=_event_id(authority_sequence),
        authority_offset=1,
    )
    return attempt, close


def _resume_record(
    close: IndexRecord,
    *,
    event_sequence: int,
    authority_sequence: int,
) -> IndexRecord:
    payload = {
        "callable_identity": "fixture.replay:run",
        "effective_implementation_identity": close.payload[
            "effective_implementation_identity"
        ],
        "engine_entry_record_id": ENGINE_ENTRY_RECORD_ID,
        "execution": {
            "job_hash": JOB_ID.removeprefix("job:"),
            "job_id": JOB_ID,
            "job_permit_id": JOB_PERMIT_ID,
            "start_record_id": START_RECORD_ID,
        },
        "repair_attempt_record_id": close.payload["attempt_record_id"],
        "repair_close_record_id": close.record_id,
        "repair_id": close.payload["repair_id"],
        "runtime_entry_record_id": None,
    }
    record_id = canonical_digest(
        domain="job-repaired-execution-resume",
        payload=payload,
    )
    return IndexRecord(
        kind="job-resumed",
        record_id=record_id,
        subject=f"Job:{JOB_ID}",
        status="validated",
        fingerprint=JOB_ID.removeprefix("job:"),
        payload=payload,
        event_stream=f"job-resume:{JOB_ID}",
        event_sequence=event_sequence,
        authority_sequence=authority_sequence,
        authority_event_id=_event_id(authority_sequence),
        authority_offset=0,
    )


def _scientific_completion(executable_id: str) -> dict[str, Any]:
    registration = {
        "alpha_ppm": 100_000,
        "criterion_id": "E01-familywise-selection",
        "family_id": "selection-family:" + "2" * 64,
        "family_registration_hash": "3" * 64,
        "family_size": len(CONCURRENT_FAMILY.executable_ids),
        "member_id": executable_id,
        "method": "bonferroni_concurrent_family.v1",
        "ordered_member_ids": list(CONCURRENT_FAMILY.executable_ids),
    }
    batch_binding = build_multiplicity_batch_binding(
        batch_id=BATCH_ID,
        concurrent_family=CONCURRENT_FAMILY.to_identity_payload(),
        selection_registration=registration,
        executable_id=executable_id,
        ordered_member_ids=CONCURRENT_FAMILY.executable_ids,
    )
    return {
        "candidate_eligible": False,
        "claims": list(SCIENTIFIC_CLAIMS),
        "evidence_depth": "discovery",
        "executed_evidence_modes": list(SCIENTIFIC_MODES),
        "executable_id": executable_id,
        "measurement_artifact_hashes": ["4" * 64],
        "multiplicity_batch_binding": batch_binding,
        "multiplicity_registrations": [registration],
        "result_manifest_hash": "5" * 64,
        "scientific_eligible": True,
        "validation_plan_hash": VALIDATION_PLAN_HASH,
        "validation_trace": {"validator_id": VALIDATOR_ID},
        "validator_id": VALIDATOR_ID,
        "verdict": "passed",
    }


def _completion_record(
    *,
    resume_record_id: str,
    scientific: object,
    authority_sequence: int = 22,
) -> IndexRecord:
    payload = {
        "candidate_execution_context": None,
        "engineering_disposition": None,
        "external": None,
        "failure": None,
        "job_id": JOB_ID,
        "output_classes": {"result": "durable_evidence"},
        "outputs": {"result": "6" * 64},
        "repair_resume_record_id": resume_record_id,
        "runtime": None,
        "scientific": scientific,
        "source": None,
        "start_record_id": "7" * 64,
    }
    identity_payload = {
        "candidate_execution_context": None,
        "external": None,
        "failure_signature": None,
        "job_id": JOB_ID,
        "outcome": "success",
        "outputs": payload["outputs"],
        "repair_resume_record_id": resume_record_id,
        "runtime": None,
        "scientific": scientific,
        "source": None,
    }
    return IndexRecord(
        kind="job-completed",
        record_id=canonical_digest(
            domain="job-completion",
            payload=identity_payload,
        ),
        subject=f"Job:{JOB_ID}",
        status="success",
        fingerprint=JOB_ID.removeprefix("job:"),
        payload=payload,
        authority_sequence=authority_sequence,
        authority_event_id=_event_id(authority_sequence),
        authority_offset=0,
    )


def _judgment_record(
    completion: IndexRecord,
    *,
    authority_sequence: int = 23,
    fingerprint: str | None = None,
    negative_memory_id: str | None = None,
) -> IndexRecord:
    payload = {
        "completion_record_id": completion.record_id,
        "negative_memory_id": negative_memory_id,
    }
    identity_payload = {
        "completion_record_id": completion.record_id,
        "disposition": "continue_batch",
        "negative_memory_id": negative_memory_id,
    }
    return IndexRecord(
        kind="job-evidence-decision",
        record_id=canonical_digest(
            domain="job-evidence-decision",
            payload=identity_payload,
        ),
        subject=f"Job:{JOB_ID}",
        status="continue_batch",
        fingerprint=(
            JOB_ID.removeprefix("job:")
            if fingerprint is None
            else fingerprint
        ),
        payload=payload,
        authority_sequence=authority_sequence,
        authority_event_id=_event_id(authority_sequence),
        authority_offset=0,
    )


def _trial_authority_records(
    *,
    executable_id: str,
    executable_manifest: dict[str, Any],
    ordinal: int,
) -> tuple[IndexRecord, IndexRecord, IndexRecord, IndexRecord]:
    authority_sequence = ordinal + 1
    global_multiplicity = ordinal
    event_id = _event_id(authority_sequence)
    result = {
        "cache_hit": False,
        "global_multiplicity": global_multiplicity,
        "trial_delta": 1,
    }
    operation_id = f"register-fixture-trial-{ordinal}"
    trial = IndexRecord(
        kind="trial",
        record_id=executable_id,
        subject=f"Batch:{BATCH_ID}",
        status="evaluated",
        fingerprint=executable_id.removeprefix("executable:"),
        payload={
            "engineering_fixture": False,
            "executable": executable_manifest,
            "material_identity": MATERIAL_IDENTITY,
            "mission_id": MISSION_ID,
            "portfolio_axis_id": None,
            "portfolio_axis_identity": None,
            "portfolio_decision_id": None,
            "portfolio_snapshot_id": None,
            "replay_obligation_ids": [OBLIGATION_ID],
            "scheduler_eligible": False,
            "scientific_eligible": True,
            "study_id": STUDY_ID,
            "trial_delta": 1,
        },
        event_stream=f"batch-trials:{BATCH_ID}",
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
            "global_multiplicity": global_multiplicity,
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
            domain="fixture-trial-operation",
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
