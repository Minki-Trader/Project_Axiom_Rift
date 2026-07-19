"""Registered inventory for a scientific validator-identity successor."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

import axiom_rift.operations.scientific_protocol_repair_inventory as base
from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.operations.repair_disposition_inventory import (
    RepairDispositionInventoryError,
    normalize_repair_inventory_facts,
)
from axiom_rift.operations.validation import (
    EngineeringRepairValidationRequest,
    EvidenceValidationError,
    ValidatedEvidence,
    validator_identity,
    validator_implementation_sha256,
)


VALIDATOR_REBIND_REPAIR_INVENTORY_PROTOCOL = (
    "scientific_validator_rebind_successor_repair_inventory.v1"
)
_THIS_IMPLEMENTATION = Path(__file__).resolve()
VALIDATOR_REBIND_REPAIR_INVENTORY_DEPENDENCIES = (
    Path(base.__file__).resolve(),
)
VALIDATOR_REBIND_REPAIR_INVENTORY_VALIDATOR_ID = validator_identity(
    protocol=VALIDATOR_REBIND_REPAIR_INVENTORY_PROTOCOL,
    domains=frozenset({"engineering"}),
    implementation_sha256=validator_implementation_sha256(
        implementation_path=_THIS_IMPLEMENTATION,
        dependency_paths=VALIDATOR_REBIND_REPAIR_INVENTORY_DEPENDENCIES,
    ),
)


def validator_rebind_successor_inventory(
    *,
    current_job_spec: Mapping[str, Any],
    proposed_job_spec: Mapping[str, Any],
    current_executable_manifest: Mapping[str, Any],
    proposed_executable_manifest: Mapping[str, Any],
    current_implementation_manifest: Mapping[str, Any],
    proposed_implementation_manifest: Mapping[str, Any],
    support_hashes: Mapping[str, str],
) -> dict[str, Any]:
    current_science = current_job_spec.get("scientific_binding")
    proposed_science = proposed_job_spec.get("scientific_binding")
    if (
        not isinstance(current_science, Mapping)
        or not isinstance(proposed_science, Mapping)
        or current_science.get("validator_id")
        == proposed_science.get("validator_id")
    ):
        raise EvidenceValidationError(
            "scientific validator successor did not rebind validator identity"
        )
    normalized_proposed = {
        **dict(proposed_job_spec),
        "scientific_binding": {
            **dict(proposed_science),
            "validator_id": current_science.get("validator_id"),
        },
    }
    inventory = base.scientific_protocol_successor_inventory(
        current_job_spec=current_job_spec,
        proposed_job_spec=normalized_proposed,
        current_executable_manifest=current_executable_manifest,
        proposed_executable_manifest=proposed_executable_manifest,
        current_implementation_manifest=current_implementation_manifest,
        proposed_implementation_manifest=proposed_implementation_manifest,
        support_hashes=support_hashes,
    )
    inventory["axes"][1]["axis_id"] = "protected-scientific-validator-protocol"
    return inventory


class ScientificValidatorRebindRepairInventoryValidator:
    validator_id = VALIDATOR_REBIND_REPAIR_INVENTORY_VALIDATOR_ID
    domains = frozenset({"engineering"})
    implementation_path = _THIS_IMPLEMENTATION
    dependency_paths = VALIDATOR_REBIND_REPAIR_INVENTORY_DEPENDENCIES
    protocol = VALIDATOR_REBIND_REPAIR_INVENTORY_PROTOCOL
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
            or request.verification_kind != "inventory"
            or request.repair_id is None
        ):
            raise EvidenceValidationError(
                "scientific validator Repair inventory is unauthorized"
            )
        by_name = {
            artifact.output_name: artifact for artifact in request.artifacts
        }
        if (
            len(by_name) != len(request.artifacts)
            or set(by_name) != base._ROLE_NAMES
        ):
            raise EvidenceValidationError(
                "scientific validator Repair artifacts are incomplete"
            )
        plan = base._document(
            by_name["validation_plan"].read_bytes(),
            label="scientific validator Repair plan",
        )
        binding = base._plain(request.binding)
        expected_roles = [
            {"output_name": name, "sha256": artifact.sha256}
            for name, artifact in sorted(by_name.items())
            if name != "validation_plan"
        ]
        context = None if not isinstance(binding, Mapping) else binding.get(
            "context"
        )
        if (
            not isinstance(binding, Mapping)
            or set(binding) != base._BINDING_FIELDS
            or binding.get("schema") != base.BINDING_SCHEMA
            or binding.get("protocol") != self.protocol
            or binding.get("verification_kind") != "inventory"
            or binding.get("mission_id") != request.mission_id
            or binding.get("artifact_roles") != expected_roles
            or not isinstance(context, Mapping)
            or set(context) != base._CONTEXT_FIELDS
            or context.get("schema")
            != "engineering_repair_inventory_context.v1"
            or context.get("scientific_semantics_changed") is not False
            or context.get("repair_attempts") != []
            or context.get("repair_validation_observations") != []
            or context.get("repair_validation_observation_head") is not None
            or context.get("accepted_attempt_head_record_id") is not None
            or set(plan) != base._PLAN_FIELDS
            or plan.get("schema") != base.PLAN_SCHEMA
            or plan.get("validator_id") != self.validator_id
            or plan.get("protocol") != self.protocol
            or plan.get("verification_kind") != "inventory"
            or plan.get("artifact_roles") != expected_roles
            or plan.get("binding_sha256")
            != sha256(canonical_bytes(binding)).hexdigest()
            or request.validation_plan_hash
            != by_name["validation_plan"].sha256
        ):
            raise EvidenceValidationError(
                "scientific validator Repair plan or context is invalid"
            )
        reproduction = context.get("reproduction_evidence_hashes")
        if reproduction != [by_name["reproduction:0000"].sha256]:
            raise EvidenceValidationError(
                "scientific validator Repair reproduction is invalid"
            )
        documents = {
            name: base._document(by_name[name].read_bytes(), label=name)
            for name in (
                "current_executable_manifest",
                "current_implementation_manifest",
                "current_job_spec",
                "proposed_executable_manifest",
                "proposed_implementation_manifest",
                "proposed_job_spec",
            )
        }
        support_hashes = {name: by_name[name].sha256 for name in documents}
        expected_inventory = validator_rebind_successor_inventory(
            current_job_spec=documents["current_job_spec"],
            proposed_job_spec=documents["proposed_job_spec"],
            current_executable_manifest=documents[
                "current_executable_manifest"
            ],
            proposed_executable_manifest=documents[
                "proposed_executable_manifest"
            ],
            current_implementation_manifest=documents[
                "current_implementation_manifest"
            ],
            proposed_implementation_manifest=documents[
                "proposed_implementation_manifest"
            ],
            support_hashes=support_hashes,
        )
        result = base._document(
            by_name["validation_result"].read_bytes(),
            label="scientific validator Repair inventory",
        )
        if result != expected_inventory:
            raise EvidenceValidationError(
                "scientific validator Repair inventory was not recomputed"
            )
        opened_hashes = tuple(
            sorted(
                artifact.sha256
                for name, artifact in by_name.items()
                if name != "validation_plan"
            )
        )
        try:
            inventory = normalize_repair_inventory_facts(
                result,
                accepted_attempts=context["repair_attempts"],
                current_basis_hash=str(context["current_basis_hash"]),
                information_set_hash=str(context["information_set_hash"]),
                opened_result_artifact_hashes=opened_hashes,
            )
        except (RepairDispositionInventoryError, TypeError, ValueError) as exc:
            raise EvidenceValidationError(str(exc)) from exc
        if base._plain(request.result_manifest) != {
            "protocol": self.protocol,
            "result_artifact_hashes": list(opened_hashes),
            "schema": "engineering_repair_validation_dispatch.v1",
            "verification_kind": "inventory",
        }:
            raise EvidenceValidationError(
                "scientific validator Repair dispatch is invalid"
            )
        for artifact in by_name.values():
            artifact.read_bytes()
        return ValidatedEvidence(
            verdict="passed",
            measurement_artifact_hashes=opened_hashes,
            artifact_roles=tuple(
                sorted(
                    (name, artifact.sha256)
                    for name, artifact in by_name.items()
                )
            ),
            facts={"binding": binding, **inventory},
            scientific_eligible=False,
            candidate_eligible=False,
            release_eligible=False,
        )


__all__ = [
    "ScientificValidatorRebindRepairInventoryValidator",
    "VALIDATOR_REBIND_REPAIR_INVENTORY_PROTOCOL",
    "VALIDATOR_REBIND_REPAIR_INVENTORY_VALIDATOR_ID",
    "validator_rebind_successor_inventory",
]
