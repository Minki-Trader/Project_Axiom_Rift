"""Production validator for an actual protected-semantic Repair exit.

Terminal disposition itself is deterministic Writer logic over the registered
domain inventory and therefore has no second generic validator.  This module
contains only the genuinely independent proof needed when a proposed repair
would alter protected scientific semantics.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

import axiom_rift.operations.repair_semantic_change_authority as semantic_module
import axiom_rift.operations.repair_validation as repair_validation_module
from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.operations.repair_semantic_change_authority import (
    RepairSemanticChangeAuthorityError,
    semantic_change_facts,
)
from axiom_rift.operations.repair_validation import BINDING_SCHEMA, PLAN_SCHEMA
from axiom_rift.operations.validation import (
    EngineeringRepairValidationRequest,
    EvidenceValidationError,
    ValidatedEvidence,
    validator_identity,
    validator_implementation_sha256,
)


ENGINEERING_SEMANTIC_CHANGE_PROTOCOL = (
    "engineering_semantic_change_necessity.v2"
)
_THIS_IMPLEMENTATION = Path(__file__).resolve()
ENGINEERING_SEMANTIC_CHANGE_VALIDATOR_DEPENDENCIES = tuple(
    sorted(
        {
            Path(semantic_module.__file__).resolve(),
            Path(repair_validation_module.__file__).resolve(),
        },
        key=lambda path: path.as_posix(),
    )
)
ENGINEERING_SEMANTIC_CHANGE_VALIDATOR_ID = validator_identity(
    protocol=ENGINEERING_SEMANTIC_CHANGE_PROTOCOL,
    domains=frozenset({"engineering"}),
    implementation_sha256=validator_implementation_sha256(
        implementation_path=_THIS_IMPLEMENTATION,
        dependency_paths=ENGINEERING_SEMANTIC_CHANGE_VALIDATOR_DEPENDENCIES,
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
_SEMANTIC_CONTEXT_FIELDS = {
    "changed_surface_count",
    "current_authority",
    "current_surface_inventory_hash",
    "proposal_sha256",
    "proposed_successor_artifact_sha256",
    "proposed_surface_inventory_hash",
    "schema",
    "scientific_semantics_changed",
    "successor_scope",
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


class EngineeringSemanticChangeNecessityValidator:
    """Prove a real diff against the exact protected scientific surfaces."""

    validator_id = ENGINEERING_SEMANTIC_CHANGE_VALIDATOR_ID
    domains = frozenset({"engineering"})
    implementation_path = _THIS_IMPLEMENTATION
    dependency_paths = ENGINEERING_SEMANTIC_CHANGE_VALIDATOR_DEPENDENCIES
    protocol = ENGINEERING_SEMANTIC_CHANGE_PROTOCOL
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
            or request.verification_kind != "semantic_change"
        ):
            raise EvidenceValidationError(
                "engineering semantic-change request is unauthorized"
            )
        by_name = {
            artifact.output_name: artifact for artifact in request.artifacts
        }
        expected_names = {
            "current_executable_manifest",
            "current_implementation_protocol",
            "current_job_spec",
            "semantic_change_case",
            "semantic_change_proposal",
            "semantic_change_successor",
            "validation_plan",
        }
        if len(by_name) != len(request.artifacts) or set(by_name) != expected_names:
            raise EvidenceValidationError(
                "engineering semantic-change evidence is incomplete"
            )
        plan_artifact = by_name["validation_plan"]
        result_artifact = by_name["semantic_change_case"]
        plan = _document(
            plan_artifact.read_bytes(),
            label="engineering semantic-change plan",
        )
        result = _document(
            result_artifact.read_bytes(),
            label="engineering semantic-change case",
        )
        binding = _plain(request.binding)
        expected_roles = [
            {"output_name": name, "sha256": artifact.sha256}
            for name, artifact in sorted(by_name.items())
            if name != "validation_plan"
        ]
        context = None if not isinstance(binding, dict) else binding.get(
            "context"
        )
        if (
            not isinstance(binding, dict)
            or set(binding) != _BINDING_FIELDS
            or binding.get("schema") != BINDING_SCHEMA
            or binding.get("protocol") != self.protocol
            or binding.get("verification_kind") != "semantic_change"
            or binding.get("mission_id") != request.mission_id
            or binding.get("artifact_roles") != expected_roles
            or set(plan) != _PLAN_FIELDS
            or plan.get("schema") != PLAN_SCHEMA
            or plan.get("validator_id") != self.validator_id
            or plan.get("protocol") != self.protocol
            or plan.get("verification_kind") != "semantic_change"
            or plan.get("artifact_roles") != expected_roles
            or plan.get("binding_sha256")
            != sha256(canonical_bytes(binding)).hexdigest()
            or request.validation_plan_hash != plan_artifact.sha256
            or not isinstance(context, dict)
            or set(context) != _SEMANTIC_CONTEXT_FIELDS
            or context.get("schema")
            != "engineering_semantic_change_context.v2"
            or context.get("scientific_semantics_changed") is not False
        ):
            raise EvidenceValidationError(
                "engineering semantic-change plan or context is invalid"
            )
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
            "verification_kind": "semantic_change",
        }:
            raise EvidenceValidationError(
                "engineering semantic-change dispatch manifest is invalid"
            )
        current_authority = context.get("current_authority")
        if not isinstance(current_authority, Mapping):
            raise EvidenceValidationError(
                "engineering semantic-change current authority is absent"
            )
        try:
            current_spec = _document(
                by_name["current_job_spec"].read_bytes(),
                label="current semantic-change Job spec",
            )
            current_executable = _document(
                by_name["current_executable_manifest"].read_bytes(),
                label="current semantic-change Executable",
            )
            current_protocol = parse_canonical(
                by_name["current_implementation_protocol"].read_bytes()
            )
            proposal = _document(
                by_name["semantic_change_proposal"].read_bytes(),
                label="semantic-change proposal",
            )
            successor = _document(
                by_name["semantic_change_successor"].read_bytes(),
                label="semantic-change successor",
            )
            facts = semantic_change_facts(
                result,
                proposal=proposal,
                mission_id=str(current_authority.get("mission_id")),
                repair_id=str(current_authority.get("repair_id")),
                job_id=str(current_authority.get("job_id")),
                job_hash=str(current_authority.get("job_hash")),
                current_basis_hash=str(
                    current_authority.get("current_basis_hash")
                ),
                accepted_attempt_head_record_id=current_authority.get(
                    "accepted_attempt_head_record_id"
                ),
                repair_validation_observation_head=current_authority.get(
                    "repair_validation_observation_head"
                ),
                current_executable_id=str(
                    current_authority.get("executable_id")
                ),
                current_implementation_identity=str(
                    current_authority.get("implementation_identity")
                ),
                current_job_spec=current_spec,
                current_executable_manifest=current_executable,
                current_implementation_protocol=str(current_protocol),
                proposed_successor_artifact=successor,
            )
        except (
            RepairSemanticChangeAuthorityError,
            TypeError,
            ValueError,
        ) as exc:
            raise EvidenceValidationError(str(exc)) from exc
        if (
            current_authority.get("job_id") != request.job_id
            or current_authority.get("job_hash") != request.job_hash
            or current_authority.get("repair_id") != request.repair_id
            or context.get("proposal_sha256")
            != by_name["semantic_change_proposal"].sha256
            or context.get("proposed_successor_artifact_sha256")
            != by_name["semantic_change_successor"].sha256
            or context.get("successor_scope")
            != successor.get("successor_scope")
            or context.get("changed_surface_count")
            != len(result.get("changed_surfaces", ()))
            or context.get("current_surface_inventory_hash")
            != result.get("current_surface_inventory_hash")
            or context.get("proposed_surface_inventory_hash")
            != result.get("proposed_surface_inventory_hash")
            or context.get("current_authority")
            != result.get("current_authority")
        ):
            raise EvidenceValidationError(
                "engineering semantic-change evidence is incomplete"
            )
        for artifact in by_name.values():
            artifact.read_bytes()
        return ValidatedEvidence(
            verdict="passed",
            measurement_artifact_hashes=declared_results,
            artifact_roles=tuple(
                (name, artifact.sha256)
                for name, artifact in by_name.items()
            ),
            facts={"binding": binding, **facts},
            scientific_eligible=False,
            candidate_eligible=False,
            release_eligible=False,
        )


__all__ = [
    "ENGINEERING_SEMANTIC_CHANGE_PROTOCOL",
    "ENGINEERING_SEMANTIC_CHANGE_VALIDATOR_DEPENDENCIES",
    "ENGINEERING_SEMANTIC_CHANGE_VALIDATOR_ID",
    "EngineeringSemanticChangeNecessityValidator",
]
