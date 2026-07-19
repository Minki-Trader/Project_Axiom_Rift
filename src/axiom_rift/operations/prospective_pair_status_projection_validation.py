"""Registered engineering proof for the STU-0124 Repair projection fix."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

import axiom_rift.operations.repair_validation as repair_validation_module
import axiom_rift.operations.running_job as running_job_module
from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.operations.repair_semantic_equivalence import (
    RepairSemanticEquivalenceError,
)
from axiom_rift.operations.repair_validation import BINDING_SCHEMA, PLAN_SCHEMA
from axiom_rift.operations.running_job import (
    _require_passed_prospective_pair_status_correction_facts,
)
from axiom_rift.operations.validation import (
    EngineeringRepairValidationRequest,
    EvidenceValidationError,
    ValidatedEvidence,
    validator_identity,
    validator_implementation_sha256,
)


PROJECTION_REPAIR_PROTOCOL = (
    "prospective_pair_status_running_job_projection_repair.v1"
)
PROJECTION_VERIFICATION_SCHEMA = (
    "prospective_pair_status_running_job_projection_verification.v1"
)
PROJECTION_PROOF_SCHEMA = (
    "prospective_pair_status_running_job_projection_proof.v1"
)
RUNNING_JOB_SOURCE_SHA256 = (
    "f0d56ea474b7fcf7c3ebd5958766ac91a503fabccc555a5c291c66c23a1d07e1"
)
STATUS_CORRECTION_VALIDATOR_ID = (
    "validator:b4be337629711282d7c6c6f3deb3de23736163bbce56ce3a523f8608e156c8e4"
)
TRACE_PAIR = {
    "new_artifact_hash": (
        "d21ad03596d7aa8b85eae0de59bee15c9f5412d70dada83ebdd19297dc614b8c"
    ),
    "old_artifact_hash": (
        "6d3109c5ad6230d6cc2dcc71c0a393c168bedf01e4fa2f274697d5dc15cd512a"
    ),
    "relative_path": "axiom_rift/research/sleeve_exposure_cap_risk_trace.py",
}

_THIS_IMPLEMENTATION = Path(__file__).resolve()
_RUNNING_JOB_SOURCE = Path(running_job_module.__file__).resolve()
PROJECTION_REPAIR_VALIDATOR_DEPENDENCIES = tuple(
    sorted(
        {
            Path(repair_validation_module.__file__).resolve(),
            _RUNNING_JOB_SOURCE,
        },
        key=lambda path: path.as_posix(),
    )
)
PROJECTION_REPAIR_VALIDATOR_ID = validator_identity(
    protocol=PROJECTION_REPAIR_PROTOCOL,
    domains=frozenset({"engineering"}),
    implementation_sha256=validator_implementation_sha256(
        implementation_path=_THIS_IMPLEMENTATION,
        dependency_paths=PROJECTION_REPAIR_VALIDATOR_DEPENDENCIES,
    ),
)

_PLAN_FIELDS = {
    "artifact_roles",
    "binding_sha256",
    "protocol",
    "schema",
    "validator_id",
    "verification_kind",
}
_BINDING_FIELDS = {
    "artifact_roles",
    "context",
    "mission_id",
    "protocol",
    "schema",
    "verification_kind",
}


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(child) for child in value]
    return value


def _document(content: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = parse_canonical(content)
    except (TypeError, ValueError) as exc:
        raise EvidenceValidationError(f"{label} is not canonical") from exc
    if not isinstance(value, dict):
        raise EvidenceValidationError(f"{label} must be an object")
    return value


def _digest(label: str, value: object) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise EvidenceValidationError(f"{label} is not a SHA-256 digest")
    return value


def projection_verification_manifest() -> dict[str, Any]:
    source = _RUNNING_JOB_SOURCE.read_bytes()
    if sha256(source).hexdigest() != RUNNING_JOB_SOURCE_SHA256:
        raise EvidenceValidationError("running Job projection source drifted")
    binding = {
        "changed_source_pair_bindings": [dict(TRACE_PAIR)],
        "claims": ["verification-claim"],
        "new_implementation_identity": "2" * 64,
        "old_implementation_identity": "1" * 64,
        "repair_id": "repair:" + "3" * 64,
        "result_manifest_hash": "4" * 64,
        "validation_plan_hash": "5" * 64,
        "validator_id": STATUS_CORRECTION_VALIDATOR_ID,
    }
    facts = {
        "changed_source_pair": dict(TRACE_PAIR),
        "covered_surface_ids": ["verification-claim"],
        "new_implementation_identity": "2" * 64,
        "old_implementation_identity": "1" * 64,
        "repair_id": "repair:" + "3" * 64,
        "result_manifest_hash": "4" * 64,
        "schema": "prospective_pair_status_encoding_correction_facts.v1",
        "source_status": "gross_exposure_cap_blocked",
        "trace_status": "risk_policy_skipped",
        "validation_plan_hash": "5" * 64,
    }
    _require_passed_prospective_pair_status_correction_facts(
        binding=binding,
        facts=facts,
    )
    tampered = {**facts, "trace_status": "gross_exposure_cap_blocked"}
    try:
        _require_passed_prospective_pair_status_correction_facts(
            binding=binding,
            facts=tampered,
        )
    except RepairSemanticEquivalenceError:
        pass
    else:
        raise EvidenceValidationError(
            "running Job projection accepted a tampered status fact"
        )
    return {
        "conformance_cases": [
            "registered_status_facts_accepted",
            "tampered_status_facts_rejected",
        ],
        "corrected_fact_schema": (
            "prospective_pair_status_encoding_correction_facts.v1"
        ),
        "protocol": PROJECTION_REPAIR_PROTOCOL,
        "running_job_source_sha256": RUNNING_JOB_SOURCE_SHA256,
        "schema": PROJECTION_VERIFICATION_SCHEMA,
        "validator_id": PROJECTION_REPAIR_VALIDATOR_ID,
        "verdict": "passed",
    }


def require_projection_verification(content: bytes) -> dict[str, Any]:
    observed = _document(content, label="running Job projection verification")
    expected = projection_verification_manifest()
    if observed != expected:
        raise EvidenceValidationError(
            "running Job projection verification is invalid"
        )
    return observed


class ProspectivePairStatusProjectionRepairValidator:
    """Derive Repair success from exact source and conformance evidence."""

    validator_id = PROJECTION_REPAIR_VALIDATOR_ID
    domains = frozenset({"engineering"})
    implementation_path = _THIS_IMPLEMENTATION
    dependency_paths = PROJECTION_REPAIR_VALIDATOR_DEPENDENCIES
    protocol = PROJECTION_REPAIR_PROTOCOL
    authority_scope = "production"

    def validate(
        self,
        request: EngineeringRepairValidationRequest,
    ) -> ValidatedEvidence:
        if (
            not isinstance(request, EngineeringRepairValidationRequest)
            or request.engineering_fixture
            or request.domain != "engineering"
            or request.validator_id != self.validator_id
            or request.verification_kind != "candidate"
            or request.repair_id is None
        ):
            raise EvidenceValidationError(
                "running Job projection Repair request is unauthorized"
            )
        by_name = {
            artifact.output_name: artifact for artifact in request.artifacts
        }
        reproduction_names = sorted(
            name for name in by_name if name.startswith("reproduction:")
        )
        if (
            len(by_name) != len(request.artifacts)
            or set(by_name)
            != {
                "projection_proof",
                "projection_source",
                "validation_plan",
                "validation_result",
                *reproduction_names,
            }
            or not reproduction_names
        ):
            raise EvidenceValidationError(
                "running Job projection Repair artifacts are incomplete"
            )
        binding = _plain(request.binding)
        context = None if not isinstance(binding, dict) else binding.get("context")
        expected_roles = [
            {"output_name": name, "sha256": artifact.sha256}
            for name, artifact in sorted(by_name.items())
            if name != "validation_plan"
        ]
        plan = _document(
            by_name["validation_plan"].read_bytes(),
            label="running Job projection Repair plan",
        )
        if (
            not isinstance(binding, dict)
            or set(binding) != _BINDING_FIELDS
            or binding.get("schema") != BINDING_SCHEMA
            or binding.get("protocol") != self.protocol
            or binding.get("verification_kind") != "candidate"
            or binding.get("mission_id") != request.mission_id
            or binding.get("artifact_roles") != expected_roles
            or not isinstance(context, dict)
            or dict(request.evidence_subject)
            != {"kind": "Repair", "id": request.repair_id}
            or set(plan) != _PLAN_FIELDS
            or plan.get("schema") != PLAN_SCHEMA
            or plan.get("validator_id") != self.validator_id
            or plan.get("protocol") != self.protocol
            or plan.get("artifact_roles") != expected_roles
            or plan.get("binding_sha256")
            != sha256(canonical_bytes(binding)).hexdigest()
            or request.validation_plan_hash
            != by_name["validation_plan"].sha256
        ):
            raise EvidenceValidationError(
                "running Job projection Repair binding is invalid"
            )
        reproduction = context.get("reproduction_evidence_hashes")
        new_evidence = context.get("new_evidence_hashes")
        proof_hash = by_name["projection_proof"].sha256
        if (
            not isinstance(reproduction, list)
            or reproduction != sorted(set(reproduction))
            or not reproduction
            or [by_name[name].sha256 for name in reproduction_names]
            != reproduction
            or not isinstance(new_evidence, list)
            or new_evidence != sorted(set(new_evidence))
            or context.get("job_id") != request.job_id
            or context.get("job_hash") != request.job_hash
            or context.get("repair_id") != request.repair_id
            or context.get("repair_axis_id") != "running-job-projection"
            or context.get("changed_dimension") != "cause"
            or context.get("scientific_semantics_changed") is not False
            or context.get("new_basis_hash") != RUNNING_JOB_SOURCE_SHA256
            or context.get("implementation_proof_hash") is not None
            or RUNNING_JOB_SOURCE_SHA256
            != by_name["projection_source"].sha256
            or proof_hash not in new_evidence
            or RUNNING_JOB_SOURCE_SHA256 not in new_evidence
            or set(reproduction).intersection(new_evidence)
        ):
            raise EvidenceValidationError(
                "running Job projection Repair context is invalid"
            )
        source = by_name["projection_source"].read_bytes()
        if sha256(source).hexdigest() != RUNNING_JOB_SOURCE_SHA256:
            raise EvidenceValidationError(
                "running Job projection Repair source is invalid"
            )
        proof = _document(
            by_name["projection_proof"].read_bytes(),
            label="running Job projection Repair proof",
        )
        if proof != {
            "changed_dimension": "cause",
            "corrected_fact_schema": (
                "prospective_pair_status_encoding_correction_facts.v1"
            ),
            "job_hash": request.job_hash,
            "job_id": request.job_id,
            "repair_id": request.repair_id,
            "running_job_source_sha256": RUNNING_JOB_SOURCE_SHA256,
            "schema": PROJECTION_PROOF_SCHEMA,
            "scientific_semantics_changed": False,
        }:
            raise EvidenceValidationError(
                "running Job projection Repair proof is invalid"
            )
        result_content = by_name["validation_result"].read_bytes()
        result = require_projection_verification(result_content)
        declared_results = tuple(
            sorted(
                artifact.sha256
                for name, artifact in by_name.items()
                if name != "validation_plan"
            )
        )
        if _plain(request.result_manifest) != {
            "protocol": self.protocol,
            "result_artifact_hashes": list(declared_results),
            "schema": "engineering_repair_validation_dispatch.v1",
            "verification_kind": "candidate",
        }:
            raise EvidenceValidationError(
                "running Job projection Repair dispatch is invalid"
            )
        for name in reproduction_names:
            by_name[name].read_bytes()
        return ValidatedEvidence(
            verdict="passed",
            measurement_artifact_hashes=declared_results,
            artifact_roles=tuple(
                sorted(
                    (name, artifact.sha256)
                    for name, artifact in by_name.items()
                )
            ),
            facts={
                "binding": binding,
                "cause_resolved": True,
                "failure_reproduced": False,
                "material_change": True,
                "mode": "repaired",
                "new_failure_manifest_hash": None,
                "reason_code": None,
            },
            scientific_eligible=False,
            candidate_eligible=False,
            release_eligible=False,
        )


__all__ = [
    "PROJECTION_PROOF_SCHEMA",
    "PROJECTION_REPAIR_PROTOCOL",
    "PROJECTION_REPAIR_VALIDATOR_DEPENDENCIES",
    "PROJECTION_REPAIR_VALIDATOR_ID",
    "ProspectivePairStatusProjectionRepairValidator",
    "RUNNING_JOB_SOURCE_SHA256",
    "projection_verification_manifest",
]
