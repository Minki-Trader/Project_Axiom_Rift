"""Management-only materialization of fixed-hold implementation Repairs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from typing import Any, Protocol

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.operations.repair_candidate import build_repair_candidate
from axiom_rift.operations.repair_observation_authority import (
    require_repair_validation_observation_stream,
)
from axiom_rift.operations.repair_validation import (
    build_repair_candidate_validation_receipt,
)
from axiom_rift.operations.repair_semantic_equivalence import (
    IMPLEMENTATION_REPAIR_V2_SCHEMA,
    fixed_hold_authority_correction_measurement,
    semantic_equivalence_result_manifest,
)
from axiom_rift.operations.running_job_context import RunningJobEvidence
from axiom_rift.research.fixed_hold_replay_runtime import (
    FixedHoldReplayRuntimeAdapter,
    materialize_fixed_hold_replay_job_implementation,
)
from axiom_rift.storage.index import LocalIndexView


class FixedHoldRepairContext(Protocol):
    """Management-only context for an interrupted implementation Repair."""

    evidence: RunningJobEvidence

    def open_stable_index(
        self,
    ) -> AbstractContextManager[
        tuple[dict[str, Any], LocalIndexView]
    ]: ...

    def plan_fixed_hold_authority_correction_repair(
        self,
        *,
        new_implementation_identity: str,
    ) -> dict[str, Any]: ...

    def resolve_fixed_hold_authority_correction_verification(
        self,
        *,
        new_implementation_identity: str,
        evidence_hashes: tuple[str, ...],
    ) -> tuple[str, ...]: ...

    def materialize_fixed_hold_repair_candidate_validation_plan(
        self,
        *,
        explanation: str,
        new_basis_hash: str,
        new_evidence_hashes: tuple[str, ...],
        implementation_proof_hash: str,
        result_artifact_hashes: tuple[str, ...],
        repair_axis_id: str,
        prior_validation_observation_head: Mapping[str, Any] | None,
        bound_validation_observations: tuple[Mapping[str, Any], ...],
    ) -> tuple[str, str, str, tuple[str, ...]]: ...


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ValueError(f"{name} must be non-empty ASCII")
    return value


def materialize_running_job_implementation_repair_proof(
    writer: FixedHoldRepairContext,
    *,
    adapter: FixedHoldReplayRuntimeAdapter | None = None,
    callable_identity: str | None = None,
    implementation_materializer: (
        Callable[[FixedHoldRepairContext], str] | None
    ) = None,
    explanation: str,
    verification_evidence_hashes: tuple[str, ...] = (),
) -> str:
    """Bind a repaired closure and independent verification to one Job."""

    reason = _ascii("running Job Repair explanation", explanation)
    if adapter is not None:
        if callable_identity is not None or implementation_materializer is not None:
            raise ValueError(
                "running Job Repair accepts an adapter or an explicit "
                "implementation binding, not both"
            )

        def materialize_implementation(context: FixedHoldRepairContext) -> str:
            return materialize_fixed_hold_replay_job_implementation(
                context,
                adapter=adapter,
            )

    else:
        _ascii("running Job Repair callable identity", callable_identity)
        if not callable(implementation_materializer):
            raise ValueError(
                "running Job Repair implementation materializer is required"
            )
        materialize_implementation = implementation_materializer
    with writer.open_stable_index() as (control, index):
        science = control.get("scientific")
        repair = None if not isinstance(science, Mapping) else science.get(
            "active_repair"
        )
        job = (
            None if not isinstance(science, Mapping) else science.get("active_job")
        )
        if (
            not isinstance(repair, Mapping)
            or not isinstance(job, Mapping)
            or job.get("status") != "interrupted_repair"
            or repair.get("job_id") != job.get("id")
        ):
            raise ValueError("implementation Repair requires one interrupted Job")
        declaration = index.get("job-declared", str(job["id"]))
        opened = index.get("repair-open", str(repair["id"]))
        prior_head = index.event_head(f"job-repair:{job['id']}")
        prior_close = (
            None
            if prior_head is None
            else index.get(prior_head.record_kind, prior_head.record_id)
        )
        attempt_records = []
        attempt_head = index.event_head(f"repair-attempt:{repair['id']}")
        if attempt_head is not None:
            for sequence in range(1, attempt_head.sequence + 1):
                record = index.event_record(
                    f"repair-attempt:{repair['id']}", sequence
                )
                if record is None:
                    raise ValueError("implementation Repair attempt stream has a gap")
                attempt_records.append(record)
        mission_id = (
            None if declaration is None else declaration.payload.get("mission_id")
        )
        if type(mission_id) is not str or opened is None:
            raise ValueError("implementation Repair Mission authority is unavailable")
        observations, observation_head = (
            require_repair_validation_observation_stream(
                index,
                repair_id=str(repair["id"]),
                job_id=str(job["id"]),
                job_hash=str(job["hash"]),
                cause_hash=str(repair["cause_hash"]),
                reproduction_evidence_hashes=opened.payload[
                    "minimum_reproduction_evidence"
                ],
                resume_action=str(repair["resume_action"]),
                mission_id=mission_id,
                expected_scope="production",
                accepted_attempts=attempt_records,
                evidence=writer.evidence,
            )
        )
    spec = None if declaration is None else declaration.payload.get("spec")
    reproduction = (
        None
        if opened is None
        else opened.payload.get("minimum_reproduction_evidence")
    )
    if not isinstance(spec, Mapping) or not isinstance(reproduction, list):
        raise ValueError("implementation Repair provenance is unavailable")
    requested_verification = tuple(sorted(set(verification_evidence_hashes)))
    if len(requested_verification) != len(verification_evidence_hashes):
        raise ValueError(
            "implementation Repair verification evidence must be unique"
        )
    previous_identity = spec.get("implementation_identity")
    if prior_close is not None:
        previous_identity = prior_close.payload.get(
            "effective_implementation_identity"
        )
    if not isinstance(previous_identity, str):
        raise ValueError("previous implementation identity is unavailable")
    new_identity = materialize_implementation(writer)
    if new_identity == previous_identity:
        raise ValueError("implementation Repair did not change source closure")
    verification_results = (
        writer.resolve_fixed_hold_authority_correction_verification(
            new_implementation_identity=new_identity,
            evidence_hashes=requested_verification,
        )
    )
    manifest = parse_canonical(writer.evidence.read_verified(new_identity))
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema") != "job_implementation_evidence.v1"
        or not isinstance(manifest.get("artifact_hashes"), list)
    ):
        raise ValueError("repaired implementation manifest is invalid")
    plan = writer.plan_fixed_hold_authority_correction_repair(
        new_implementation_identity=new_identity,
    )
    plan_artifact = writer.evidence.finalize(canonical_bytes(plan))
    measurement_hashes: list[str] = []
    for pair in plan["changed_source_pair_bindings"]:
        measurement = writer.evidence.finalize(
            canonical_bytes(
                fixed_hold_authority_correction_measurement(
                    validation_plan_hash=plan_artifact.sha256,
                    relative_path=pair["relative_path"],
                    old_artifact_hash=pair["old_artifact_hash"],
                    new_artifact_hash=pair["new_artifact_hash"],
                )
            )
        )
        measurement_hashes.append(measurement.sha256)
    measurements = tuple(sorted(measurement_hashes))
    result = semantic_equivalence_result_manifest(
        plan=plan,
        validation_plan_hash=plan_artifact.sha256,
        measurement_artifact_hashes=measurements,
        surface_verdicts={
            surface_id: "passed" for surface_id in plan["claims"]
        },
    )
    result_artifact = writer.evidence.finalize(canonical_bytes(result))
    new_evidence = sorted(
        {
            new_identity,
            *manifest["artifact_hashes"],
            plan_artifact.sha256,
            result_artifact.sha256,
            *measurements,
        }
    )
    inner_proof = writer.evidence.finalize(
        canonical_bytes(
            {
                "changed_dimension": "implementation",
                "explanation": reason,
                "job_hash": job["hash"],
                "job_id": job["id"],
                "new_evidence_hashes": new_evidence,
                "new_implementation_identity": new_identity,
                "previous_implementation_identity": previous_identity,
                "repair_id": repair["id"],
                "reproduction_evidence_hashes": sorted(reproduction),
                "schema": IMPLEMENTATION_REPAIR_V2_SCHEMA,
                "semantic_equivalence_measurement_artifact_hashes": list(
                    measurements
                ),
                "semantic_equivalence_result_manifest_hash": (
                    result_artifact.sha256
                ),
                "semantic_equivalence_validation_plan_hash": (
                    plan_artifact.sha256
                ),
                "semantic_equivalence_validator_id": plan["validator_id"],
            }
        )
    )
    bound_observations = tuple(
        {
            "new_information_evidence_hashes": list(
                item["new_information_evidence_hashes"]
            ),
            "observation_record_id": item["observation_record_id"],
        }
        for item in observations
    )
    observation_information = {
        identity
        for item in bound_observations
        for identity in item["new_information_evidence_hashes"]
    }
    attempt_new_evidence = tuple(
        sorted({inner_proof.sha256, *new_evidence, *observation_information})
    )
    (
        check_plan_hash,
        repair_validator_id,
        verification_protocol,
        repair_validation_artifact_hashes,
    ) = (
        writer.materialize_fixed_hold_repair_candidate_validation_plan(
            explanation=reason,
            new_basis_hash=new_identity,
            new_evidence_hashes=attempt_new_evidence,
            implementation_proof_hash=inner_proof.sha256,
            result_artifact_hashes=verification_results,
            repair_axis_id="implementation-source-closure",
            prior_validation_observation_head=observation_head,
            bound_validation_observations=bound_observations,
        )
    )
    verification_receipt = writer.evidence.finalize(
        canonical_bytes(
            build_repair_candidate_validation_receipt(
                validator_id=repair_validator_id,
                validation_plan_hash=check_plan_hash,
                protocol=verification_protocol,
                result_artifact_hashes=(
                    repair_validation_artifact_hashes
                ),
            )
        )
    )
    verification = (verification_receipt.sha256,)
    if set(reproduction).intersection(attempt_new_evidence) or set(
        reproduction
    ).intersection(
        {check_plan_hash, *verification_results, *verification}
    ) or set(attempt_new_evidence).intersection(
        {check_plan_hash, *verification_results, *verification}
    ):
        raise ValueError(
            "implementation Repair evidence surfaces must be distinct"
        )
    candidate = writer.evidence.finalize(
        canonical_bytes(
            build_repair_candidate(
                cause_hash=repair["cause_hash"],
                changed_dimension="implementation",
                repair_axis_id="implementation-source-closure",
                explanation=reason,
                implementation_proof_hash=inner_proof.sha256,
                job_hash=job["hash"],
                job_id=job["id"],
                new_basis_hash=new_identity,
                new_evidence_hashes=attempt_new_evidence,
                previous_basis_hash=repair["latest_basis_hash"],
                prior_attempt_record_id=repair["latest_attempt_record_id"],
                prior_validation_observation_head=observation_head,
                bound_validation_observations=bound_observations,
                repair_id=repair["id"],
                reproduction_evidence_hashes=tuple(sorted(reproduction)),
                resume_action=repair["resume_action"],
                verification_evidence_hashes=verification,
            )
        )
    )
    return candidate.sha256


__all__ = [
    "FixedHoldRepairContext",
    "materialize_running_job_implementation_repair_proof",
]
