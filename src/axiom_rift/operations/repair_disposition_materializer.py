"""Two-phase materialization for one validator-derived Repair terminal.

The stable repository head is read only long enough to freeze the Repair
information set.  Registered domain validators then execute after that lock
has been released.  Their actual facts, never a caller-authored disposition,
drive the deterministic terminal derivation.  The resulting in-process
capability can be consumed only while the exact stable head still matches.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import AbstractContextManager
from typing import Any, Protocol

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.operations.repair_disposition_case import (
    REPAIR_DISPOSITION_CASE_SCHEMA,
    RepairDispositionCaseError,
    derive_repair_disposition,
    normalize_repair_disposition_case,
)
from axiom_rift.operations.repair_observation_authority import (
    require_repair_validation_observation_stream,
)
from axiom_rift.operations.repair_protocol import (
    EngineeringFailureDisposition,
    RepairProtocolError,
    parse_engineering_failure_disposition,
)
from axiom_rift.operations.repair_semantic_change_authority import (
    RepairSemanticChangeAuthorityError,
    build_semantic_change_proposal,
    derive_semantic_change_case,
    normalize_semantic_change_successor_artifact,
)
from axiom_rift.operations.repair_disposition_validation import (
    ENGINEERING_SEMANTIC_CHANGE_PROTOCOL,
    ENGINEERING_SEMANTIC_CHANGE_VALIDATOR_ID,
)
from axiom_rift.operations.repair_validation import (
    DISPOSITION_DERIVATION_SCHEMA,
    RepairValidationError,
    build_repair_inventory_authority_head,
    build_repair_inventory_validation_context,
    build_repair_inventory_validation_receipt,
    build_repair_validation_plan,
    build_semantic_change_validation_receipt,
    repair_validation_binding,
    require_stored_accepted_repair_candidate_attempt,
    validate_engineering_disposition,
    validate_repair_inventory,
    validate_semantic_change_necessity,
)
from axiom_rift.operations.validation import EvidenceValidatorRegistry
from axiom_rift.storage.evidence import EvidenceStore
from axiom_rift.storage.index import LocalIndexView


class RepairDispositionContext(Protocol):
    """Public Writer boundary used by the standalone convenience function."""

    def materialize_engineering_repair_disposition(
        self,
        *,
        inventory_validator_id: str,
        inventory_protocol: str,
        inventory_result_artifacts: Mapping[str, str],
        rationale: str,
        resume_condition: str,
        semantic_change_successor_artifact_hash: str | None = None,
    ) -> str: ...


class _RepairDispositionWriter(Protocol):
    evidence: EvidenceStore
    engineering_fixture: bool
    validation_registry: EvidenceValidatorRegistry

    def open_stable_index(
        self,
    ) -> AbstractContextManager[
        tuple[dict[str, Any], LocalIndexView]
    ]: ...

    def _install_engineering_repair_disposition_capability(
        self,
        *,
        _writer_token: object,
        expected_control_hash: str,
        disposition_hash: str,
        disposition: EngineeringFailureDisposition,
        disposition_validation: Mapping[str, Any],
    ) -> str: ...


def _inventory_result_roles(
    writer: _RepairDispositionWriter,
    value: Mapping[str, str],
) -> tuple[tuple[str, str], ...]:
    roles: list[tuple[str, str]] = []
    for name, identity in value.items():
        if (
            type(name) is not str
            or not name
            or not name.isascii()
            or name == "validation_plan"
            or type(identity) is not str
        ):
            raise RepairDispositionCaseError(
                "Repair inventory result roles are invalid"
            )
        writer.evidence.verify(identity)
        roles.append((name, identity))
    normalized = tuple(sorted(roles))
    if (
        not normalized
        or len({name for name, _identity in normalized}) != len(normalized)
        or len({identity for _name, identity in normalized}) != len(normalized)
    ):
        raise RepairDispositionCaseError(
            "Repair inventory result roles must be content-distinct"
        )
    return normalized


def _semantic_receipt(
    writer: _RepairDispositionWriter,
    *,
    mission_id: str,
    job_id: str,
    job_hash: str,
    repair_id: str,
    current_basis_hash: str,
    accepted_attempt_head_record_id: str | None,
    observation_head: Mapping[str, Any] | None,
    current_executable_id: str,
    current_implementation_identity: str,
    current_job_spec: Mapping[str, Any],
    current_executable_manifest: Mapping[str, Any],
    current_implementation_protocol: str,
    successor_artifact_hash: str,
) -> tuple[str, str]:
    writer.validation_registry.require_plannable_protocol(
        validator_id=ENGINEERING_SEMANTIC_CHANGE_VALIDATOR_ID,
        domain="engineering",
        protocol=ENGINEERING_SEMANTIC_CHANGE_PROTOCOL,
    )
    try:
        successor = normalize_semantic_change_successor_artifact(
            writer.evidence.read_verified(successor_artifact_hash)
        )
        proposal = build_semantic_change_proposal(
            mission_id=mission_id,
            repair_id=repair_id,
            job_id=job_id,
            job_hash=job_hash,
            current_basis_hash=current_basis_hash,
            accepted_attempt_head_record_id=accepted_attempt_head_record_id,
            repair_validation_observation_head=observation_head,
            current_executable_id=current_executable_id,
            current_implementation_identity=current_implementation_identity,
            current_job_spec=current_job_spec,
            current_executable_manifest=current_executable_manifest,
            current_implementation_protocol=current_implementation_protocol,
            proposed_successor_artifact=successor,
        )
        case = derive_semantic_change_case(
            proposal=proposal,
            mission_id=mission_id,
            repair_id=repair_id,
            job_id=job_id,
            job_hash=job_hash,
            current_basis_hash=current_basis_hash,
            accepted_attempt_head_record_id=accepted_attempt_head_record_id,
            repair_validation_observation_head=observation_head,
            current_executable_id=current_executable_id,
            current_implementation_identity=current_implementation_identity,
            current_job_spec=current_job_spec,
            current_executable_manifest=current_executable_manifest,
            current_implementation_protocol=current_implementation_protocol,
            proposed_successor_artifact=successor,
        )
    except RepairSemanticChangeAuthorityError as exc:
        raise RepairDispositionCaseError(str(exc)) from exc
    successor_artifact = writer.evidence.finalize(canonical_bytes(successor))
    if successor_artifact.sha256 != successor_artifact_hash:
        raise RepairDispositionCaseError(
            "semantic-change successor artifact identity differs"
        )
    proposal_artifact = writer.evidence.finalize(canonical_bytes(proposal))
    case_artifact = writer.evidence.finalize(canonical_bytes(case))
    current_job_spec_artifact = writer.evidence.finalize(
        canonical_bytes(dict(current_job_spec))
    )
    current_executable_artifact = writer.evidence.finalize(
        canonical_bytes(dict(current_executable_manifest))
    )
    current_protocol_artifact = writer.evidence.finalize(
        canonical_bytes(current_implementation_protocol)
    )
    roles = sorted(
        [
            ("current_executable_manifest", current_executable_artifact.sha256),
            ("current_implementation_protocol", current_protocol_artifact.sha256),
            ("current_job_spec", current_job_spec_artifact.sha256),
            ("semantic_change_case", case_artifact.sha256),
            ("semantic_change_proposal", proposal_artifact.sha256),
            ("semantic_change_successor", successor_artifact.sha256),
        ]
    )
    if len({identity for _name, identity in roles}) != len(roles):
        raise RepairDispositionCaseError(
            "semantic-change evidence roles must be content-distinct"
        )
    context = {
        "changed_surface_count": len(case["changed_surfaces"]),
        "current_authority": dict(case["current_authority"]),
        "current_surface_inventory_hash": case[
            "current_surface_inventory_hash"
        ],
        "proposal_sha256": proposal_artifact.sha256,
        "proposed_successor_artifact_sha256": successor_artifact.sha256,
        "proposed_surface_inventory_hash": case[
            "proposed_surface_inventory_hash"
        ],
        "schema": "engineering_semantic_change_context.v2",
        "scientific_semantics_changed": False,
        "successor_scope": successor["successor_scope"],
    }
    binding = repair_validation_binding(
        verification_kind="semantic_change",
        mission_id=mission_id,
        protocol=ENGINEERING_SEMANTIC_CHANGE_PROTOCOL,
        context=context,
        artifact_roles=roles,
    )
    plan = writer.evidence.finalize(
        canonical_bytes(
            build_repair_validation_plan(
                validator_id=ENGINEERING_SEMANTIC_CHANGE_VALIDATOR_ID,
                binding=binding,
            )
        )
    )
    receipt = writer.evidence.finalize(
        canonical_bytes(
            build_semantic_change_validation_receipt(
                validator_id=ENGINEERING_SEMANTIC_CHANGE_VALIDATOR_ID,
                validation_plan_hash=plan.sha256,
                protocol=ENGINEERING_SEMANTIC_CHANGE_PROTOCOL,
                result_artifact_hashes=tuple(
                    sorted(identity for _name, identity in roles)
                ),
            )
        )
    )
    return receipt.sha256, str(successor["successor_scope"])


def _materialize_engineering_repair_disposition(
    writer: _RepairDispositionWriter,
    *,
    _writer_token: object,
    inventory_validator_id: str,
    inventory_protocol: str,
    inventory_result_artifacts: Mapping[str, str],
    rationale: str,
    resume_condition: str,
    semantic_change_successor_artifact_hash: str | None = None,
) -> str:
    """Internal implementation entered only through ``StateWriter``."""

    expected_scope = (
        "fixture_only" if writer.engineering_fixture else "production"
    )
    if writer.engineering_fixture and (
        semantic_change_successor_artifact_hash is not None
    ):
        raise RepairDispositionCaseError(
            "fixture disposition cannot mint production semantic authority"
        )
    writer.validation_registry.require_plannable_protocol(
        validator_id=inventory_validator_id,
        domain="engineering",
        protocol=inventory_protocol,
    )
    inventory_roles = _inventory_result_roles(
        writer, inventory_result_artifacts
    )
    if (
        type(rationale) is not str
        or not rationale
        or not rationale.isascii()
        or type(resume_condition) is not str
        or not resume_condition
        or not resume_condition.isascii()
    ):
        raise RepairDispositionCaseError(
            "engineering disposition rationale and resume condition must be ASCII"
        )

    with writer.open_stable_index() as (control, index):
        science = control.get("scientific")
        repair = None if not isinstance(science, Mapping) else science.get(
            "active_repair"
        )
        job = None if not isinstance(science, Mapping) else science.get(
            "active_job"
        )
        mission_id = (
            None
            if not isinstance(science, Mapping)
            else science.get("active_mission")
        )
        if (
            not isinstance(repair, Mapping)
            or not isinstance(job, Mapping)
            or type(mission_id) is not str
            or job.get("status") != "interrupted_repair"
            or repair.get("job_id") != job.get("id")
        ):
            raise RepairDispositionCaseError(
                "terminal Repair decision requires one interrupted Job"
            )
        repair_id = str(repair["id"])
        job_id = str(job["id"])
        job_hash = str(job["hash"])
        cause_hash = str(repair["cause_hash"])
        opened = index.get("repair-open", repair_id)
        if opened is None:
            raise RepairDispositionCaseError("Repair open authority is absent")
        reproduction = tuple(
            opened.payload.get("minimum_reproduction_evidence", ())
        )

        current_job_spec: dict[str, Any] | None = None
        current_executable_id: str | None = None
        current_executable_manifest: dict[str, Any] | None = None
        current_implementation_identity: str | None = None
        current_implementation_protocol: str | None = None
        if semantic_change_successor_artifact_hash is not None:
            declaration = index.get("job-declared", job_id)
            spec_value = (
                None if declaration is None else declaration.payload.get("spec")
            )
            subject = (
                None
                if not isinstance(spec_value, Mapping)
                else spec_value.get("evidence_subject")
            )
            executable_id = (
                None
                if not isinstance(subject, Mapping)
                or subject.get("kind") != "Executable"
                else subject.get("id")
            )
            trial = (
                None
                if type(executable_id) is not str
                else index.get("trial", executable_id)
            )
            executable_value = (
                None if trial is None else trial.payload.get("executable")
            )
            implementation_identity = (
                None
                if not isinstance(spec_value, Mapping)
                else spec_value.get("implementation_identity")
            )
            try:
                implementation_manifest = (
                    None
                    if type(implementation_identity) is not str
                    else parse_canonical(
                        writer.evidence.read_verified(implementation_identity)
                    )
                )
            except (FileNotFoundError, OSError, TypeError, ValueError) as exc:
                raise RepairDispositionCaseError(
                    "current implementation protocol is unavailable"
                ) from exc
            if (
                declaration is None
                or declaration.fingerprint != job_hash
                or not isinstance(spec_value, Mapping)
                or type(executable_id) is not str
                or trial is None
                or not isinstance(executable_value, Mapping)
                or not isinstance(implementation_manifest, Mapping)
                or implementation_manifest.get("schema")
                != "job_implementation_evidence.v1"
                or implementation_manifest.get("callable_identity")
                != spec_value.get("callable_identity")
                or type(implementation_manifest.get("protocol")) is not str
            ):
                raise RepairDispositionCaseError(
                    "semantic-change proposal lacks current Executable authority"
                )
            current_job_spec = dict(spec_value)
            current_executable_id = executable_id
            current_executable_manifest = dict(executable_value)
            current_implementation_identity = str(implementation_identity)
            current_implementation_protocol = str(
                implementation_manifest["protocol"]
            )

        stream = f"repair-attempt:{repair_id}"
        head = index.event_head(stream)
        attempt_records = []
        if head is not None:
            for sequence in range(1, head.sequence + 1):
                record = index.event_record(stream, sequence)
                if record is None or record.status != "failed":
                    raise RepairDispositionCaseError(
                        "terminal Repair decision requires only failed attempts"
                    )
                attempt_records.append(record)
        observations, observation_head = (
            require_repair_validation_observation_stream(
                index,
                repair_id=repair_id,
                job_id=job_id,
                job_hash=job_hash,
                cause_hash=cause_hash,
                reproduction_evidence_hashes=reproduction,
                resume_action=str(opened.payload["resume_action"]),
                mission_id=mission_id,
                expected_scope=expected_scope,
                accepted_attempts=attempt_records,
                evidence=writer.evidence,
            )
        )
        attempts: list[dict[str, Any]] = []
        validated_attempts: list[dict[str, Any]] = []
        observation_stream = f"repair-validation-observation:{repair_id}"
        for record in attempt_records:
            bound_observations: list[dict[str, Any]] = []
            prior_observation_head: dict[str, Any] | None = None
            for observation in observations:
                observation_record = index.event_record(
                    observation_stream,
                    int(observation["observation_sequence"]),
                )
                if (
                    observation_record is None
                    or type(observation_record.authority_sequence) is not int
                    or type(record.authority_sequence) is not int
                ):
                    raise RepairDispositionCaseError(
                        "Repair inventory observation chronology is malformed"
                    )
                if observation_record.authority_sequence >= record.authority_sequence:
                    break
                bound_observations.append(
                    {
                        "new_information_evidence_hashes": list(
                            observation["new_information_evidence_hashes"]
                        ),
                        "observation_record_id": observation_record.record_id,
                    }
                )
                prior_observation_head = {
                    "fingerprint": observation_record.fingerprint,
                    "record_id": observation_record.record_id,
                    "sequence": observation_record.event_sequence,
                }
            candidate, validation = (
                require_stored_accepted_repair_candidate_attempt(
                    attempt_payload=record.payload,
                    mission_id=mission_id,
                    evidence=writer.evidence,
                    expected_scope=expected_scope,
                    expected_prior_validation_observation_head=(
                        prior_observation_head
                    ),
                    expected_bound_validation_observations=(
                        bound_observations
                    ),
                )
            )
            entry = {
                "attempt_proof_hash": candidate.sha256,
                "changed_dimension": candidate.changed_dimension,
                "new_basis_hash": candidate.new_basis_hash,
                "repair_attempt_record_id": record.record_id,
                "repair_axis_id": candidate.repair_axis_id,
                "verification_receipt_hashes": list(
                    candidate.verification_evidence_hashes
                ),
            }
            attempts.append(entry)
            validated_attempts.append(
                {**entry, "repair_validation": validation}
            )
        authority_head = build_repair_inventory_authority_head(control)

    current_basis_hash = (
        cause_hash if not attempts else str(attempts[-1]["new_basis_hash"])
    )
    attempt_head_id = (
        None
        if not attempts
        else str(attempts[-1]["repair_attempt_record_id"])
    )
    inventory_context = build_repair_inventory_validation_context(
        job_id=job_id,
        job_hash=job_hash,
        repair_id=repair_id,
        cause_hash=cause_hash,
        current_basis_hash=current_basis_hash,
        accepted_attempts=validated_attempts,
        repair_validation_observations=observations,
        repair_validation_observation_head=observation_head,
        reproduction_evidence_hashes=reproduction,
        authority_head=authority_head,
    )
    inventory_binding = repair_validation_binding(
        verification_kind="inventory",
        mission_id=mission_id,
        protocol=inventory_protocol,
        context=inventory_context,
        artifact_roles=inventory_roles,
    )
    inventory_plan = writer.evidence.finalize(
        canonical_bytes(
            build_repair_validation_plan(
                validator_id=inventory_validator_id,
                binding=inventory_binding,
            )
        )
    )
    inventory_receipt = writer.evidence.finalize(
        canonical_bytes(
            build_repair_inventory_validation_receipt(
                validator_id=inventory_validator_id,
                validation_plan_hash=inventory_plan.sha256,
                protocol=inventory_protocol,
                result_artifact_hashes=tuple(
                    sorted(identity for _name, identity in inventory_roles)
                ),
            )
        )
    )

    # Registered domain work occurs after the stable-state read lock is gone.
    inventory_validation, inventory = validate_repair_inventory(
        receipt_hash=inventory_receipt.sha256,
        mission_id=mission_id,
        job_id=job_id,
        job_hash=job_hash,
        repair_id=repair_id,
        cause_hash=cause_hash,
        current_basis_hash=current_basis_hash,
        accepted_attempts=validated_attempts,
        repair_validation_observations=observations,
        repair_validation_observation_head=observation_head,
        reproduction_evidence_hashes=reproduction,
        authority_head=authority_head,
        evidence=writer.evidence,
        registry=writer.validation_registry,
        engineering_fixture=writer.engineering_fixture,
    )
    inventory_facts_artifact = writer.evidence.finalize(
        canonical_bytes(inventory)
    )

    semantic_receipt_hash: str | None = None
    semantic_validation: dict[str, Any] | None = None
    successor_scope: str | None = None
    if semantic_change_successor_artifact_hash is not None:
        if (
            current_job_spec is None
            or current_executable_id is None
            or current_executable_manifest is None
            or current_implementation_identity is None
            or current_implementation_protocol is None
        ):
            raise RepairDispositionCaseError(
                "semantic-change current authority is incomplete"
            )
        semantic_receipt_hash, successor_scope = _semantic_receipt(
            writer,
            mission_id=mission_id,
            job_id=job_id,
            job_hash=job_hash,
            repair_id=repair_id,
            current_basis_hash=current_basis_hash,
            accepted_attempt_head_record_id=attempt_head_id,
            observation_head=observation_head,
            current_executable_id=current_executable_id,
            current_implementation_identity=current_implementation_identity,
            current_job_spec=current_job_spec,
            current_executable_manifest=current_executable_manifest,
            current_implementation_protocol=current_implementation_protocol,
            successor_artifact_hash=semantic_change_successor_artifact_hash,
        )
        semantic_validation = validate_semantic_change_necessity(
            receipt_hash=semantic_receipt_hash,
            mission_id=mission_id,
            job_id=job_id,
            job_hash=job_hash,
            repair_id=repair_id,
            cause_hash=cause_hash,
            current_basis_hash=current_basis_hash,
            accepted_attempt_head_record_id=attempt_head_id,
            repair_validation_observation_head=observation_head,
            successor_scope=successor_scope,
            evidence=writer.evidence,
            registry=writer.validation_registry,
            engineering_fixture=writer.engineering_fixture,
        )

    case = normalize_repair_disposition_case(
        {
            "inventory_facts_artifact_hash": (
                inventory_facts_artifact.sha256
            ),
            "inventory_validation_receipt_hash": inventory_receipt.sha256,
            "schema": REPAIR_DISPOSITION_CASE_SCHEMA,
            "semantic_change_receipt_hash": semantic_receipt_hash,
        }
    )
    disposition_name, basis, _facts = derive_repair_disposition(
        inventory,
        observation_count=len(observations),
        scientific_semantics_change_proven=semantic_validation is not None,
    )
    if disposition_name == "requires_scientific_change":
        if successor_scope not in {"executable", "study"}:
            raise RepairDispositionCaseError(
                "scientific-change disposition requires successor scope"
            )
    elif successor_scope is not None:
        raise RepairDispositionCaseError(
            "engineering-only disposition cannot name successor scope"
        )

    case_artifact = writer.evidence.finalize(canonical_bytes(case))
    derivation_roles = [
        ("inventory_facts", inventory_facts_artifact.sha256),
        ("inventory_validation_receipt", inventory_receipt.sha256),
        ("validation_result", case_artifact.sha256),
    ]
    if semantic_receipt_hash is not None:
        derivation_roles.append(
            ("semantic_change_receipt", semantic_receipt_hash)
        )
    derivation_roles = sorted(derivation_roles)
    if len({identity for _name, identity in derivation_roles}) != len(
        derivation_roles
    ):
        raise RepairDispositionCaseError(
            "engineering disposition derivation evidence is not independent"
        )
    derivation_context = {
        "authority_head": authority_head,
        "inventory_validation_receipt_hash": inventory_receipt.sha256,
        "semantic_change_receipt_hash": semantic_receipt_hash,
        "schema": DISPOSITION_DERIVATION_SCHEMA,
    }
    derivation_binding = repair_validation_binding(
        verification_kind="disposition",
        mission_id=mission_id,
        protocol=DISPOSITION_DERIVATION_SCHEMA,
        context=derivation_context,
        artifact_roles=derivation_roles,
    )
    derivation_plan = writer.evidence.finalize(
        canonical_bytes(
            build_repair_validation_plan(
                validator_id=inventory_validator_id,
                binding=derivation_binding,
            )
        )
    )
    result_hashes = sorted(
        identity for _name, identity in derivation_roles
    )
    observation = writer.evidence.finalize(
        canonical_bytes(
            {
                "cause_hash": cause_hash,
                "check_plan_hash": derivation_plan.sha256,
                "disposition": disposition_name,
                "job_hash": job_hash,
                "job_id": job_id,
                "minimum_reproduction_evidence_hashes": sorted(reproduction),
                "repair_attempts": attempts,
                "repair_id": repair_id,
                "result_artifact_hashes": result_hashes,
                "schema": "engineering_failure_disposition_observation.v1",
                "scientific_semantics_changed": False,
                "verification_method": DISPOSITION_DERIVATION_SCHEMA,
                "verification_result": {
                    "repair_exhausted_changed_causes": (
                        "changed_causes_exhausted"
                    ),
                    "repair_infeasible": "repair_infeasible",
                    "repair_nonpositive_expected_value": (
                        "nonpositive_expected_value"
                    ),
                    "requires_scientific_change": (
                        "scientific_change_required"
                    ),
                }[disposition_name],
            }
        )
    )
    basis_artifact = writer.evidence.finalize(
        canonical_bytes(
            {
                "cause_hash": cause_hash,
                "disposition": disposition_name,
                "expected_value": basis["expected_value"],
                "job_id": job_id,
                "observation_manifest_hash": observation.sha256,
                "remaining_changed_causes": basis[
                    "remaining_changed_causes"
                ],
                "repair_id": repair_id,
                "repairable_without_scientific_change": basis[
                    "repairable_without_scientific_change"
                ],
                "schema": "engineering_failure_disposition_basis.v1",
                "scientific_semantics_change_required": basis[
                    "scientific_semantics_change_required"
                ],
            }
        )
    )
    artifact = writer.evidence.finalize(
        canonical_bytes(
            {
                "basis_manifest_hash": basis_artifact.sha256,
                "cause_hash": cause_hash,
                "disposition": disposition_name,
                "job_id": job_id,
                "rationale": rationale,
                "repair_id": repair_id,
                "repair_attempt_record_ids": [
                    item["repair_attempt_record_id"] for item in attempts
                ],
                "resume_condition": resume_condition,
                "schema": "engineering_failure_disposition.v1",
                "successor_scope": successor_scope,
            }
        )
    )
    try:
        disposition = parse_engineering_failure_disposition(
            writer.evidence.read_verified(artifact.sha256),
            job_id=job_id,
            job_hash=job_hash,
            repair_id=repair_id,
            cause_hash=cause_hash,
            reproduction_evidence_hashes=reproduction,
            repair_attempts=attempts,
            read_evidence=writer.evidence.read_verified,
            verify_evidence=writer.evidence.verify,
        )
        disposition_validation = validate_engineering_disposition(
            disposition=disposition,
            mission_id=mission_id,
            job_hash=job_hash,
            reproduction_evidence_hashes=reproduction,
            repair_attempts=validated_attempts,
            repair_validation_observations=observations,
            repair_validation_observation_head=observation_head,
            authority_head=authority_head,
            evidence=writer.evidence,
            registry=writer.validation_registry,
            engineering_fixture=writer.engineering_fixture,
            prevalidated_inventory=(inventory_validation, inventory),
            prevalidated_semantic_change=semantic_validation,
        )
    except (
        RepairProtocolError,
        RepairValidationError,
        FileNotFoundError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        raise RepairDispositionCaseError(str(exc)) from exc
    return writer._install_engineering_repair_disposition_capability(
        _writer_token=_writer_token,
        expected_control_hash=str(authority_head["control_hash"]),
        disposition_hash=artifact.sha256,
        disposition=disposition,
        disposition_validation=disposition_validation,
    )


def materialize_engineering_repair_disposition(
    writer: RepairDispositionContext,
    *,
    inventory_validator_id: str,
    inventory_protocol: str,
    inventory_result_artifacts: Mapping[str, str],
    rationale: str,
    resume_condition: str,
    semantic_change_successor_artifact_hash: str | None = None,
) -> str:
    """Enter the Writer-owned two-phase terminal materializer."""

    return writer.materialize_engineering_repair_disposition(
        inventory_validator_id=inventory_validator_id,
        inventory_protocol=inventory_protocol,
        inventory_result_artifacts=inventory_result_artifacts,
        rationale=rationale,
        resume_condition=resume_condition,
        semantic_change_successor_artifact_hash=(
            semantic_change_successor_artifact_hash
        ),
    )


__all__ = [
    "RepairDispositionContext",
    "materialize_engineering_repair_disposition",
]
