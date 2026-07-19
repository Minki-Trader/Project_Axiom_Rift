"""Production inventory validator for a protected-protocol Job successor."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

import axiom_rift.operations.repair_disposition_inventory as inventory_module
import axiom_rift.operations.repair_validation as repair_validation_module
from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.repair_disposition_inventory import (
    RepairDispositionInventoryError,
    normalize_repair_inventory_facts,
)
from axiom_rift.operations.repair_validation import BINDING_SCHEMA, PLAN_SCHEMA
from axiom_rift.operations.validation import (
    EngineeringRepairValidationRequest,
    EvidenceValidationError,
    ValidatedEvidence,
    validator_identity,
    validator_implementation_sha256,
)


SCIENTIFIC_PROTOCOL_REPAIR_INVENTORY_PROTOCOL = (
    "scientific_protocol_successor_repair_inventory.v1"
)
_THIS_IMPLEMENTATION = Path(__file__).resolve()
SCIENTIFIC_PROTOCOL_REPAIR_INVENTORY_DEPENDENCIES = tuple(
    sorted(
        {
            Path(inventory_module.__file__).resolve(),
            Path(repair_validation_module.__file__).resolve(),
        },
        key=lambda path: path.as_posix(),
    )
)
SCIENTIFIC_PROTOCOL_REPAIR_INVENTORY_VALIDATOR_ID = validator_identity(
    protocol=SCIENTIFIC_PROTOCOL_REPAIR_INVENTORY_PROTOCOL,
    domains=frozenset({"engineering"}),
    implementation_sha256=validator_implementation_sha256(
        implementation_path=_THIS_IMPLEMENTATION,
        dependency_paths=SCIENTIFIC_PROTOCOL_REPAIR_INVENTORY_DEPENDENCIES,
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
_CONTEXT_FIELDS = {
    "accepted_attempt_head_record_id",
    "authority_head",
    "cause_hash",
    "current_basis_hash",
    "information_set_hash",
    "job_hash",
    "job_id",
    "repair_attempts",
    "repair_id",
    "repair_validation_observation_head",
    "repair_validation_observations",
    "reproduction_evidence_hashes",
    "schema",
    "scientific_semantics_changed",
}
_ROLE_NAMES = {
    "current_executable_manifest",
    "current_implementation_manifest",
    "current_job_spec",
    "proposed_executable_manifest",
    "proposed_implementation_manifest",
    "proposed_job_spec",
    "reproduction:0000",
    "validation_plan",
    "validation_result",
}


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(child) for key, child in value.items()}
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


def _executable_identity(manifest: Mapping[str, Any]) -> str:
    return "executable:" + canonical_digest(
        domain="executable",
        payload=dict(manifest),
    )


def _subject(spec: Mapping[str, Any], *, label: str) -> str:
    subject = spec.get("evidence_subject")
    if (
        not isinstance(subject, Mapping)
        or subject.get("kind") != "Executable"
        or type(subject.get("id")) is not str
    ):
        raise EvidenceValidationError(f"{label} subject is not an Executable")
    return str(subject["id"])


def _implementation(
    spec: Mapping[str, Any],
    manifest: Mapping[str, Any],
    *,
    label: str,
) -> str:
    identity = spec.get("implementation_identity")
    if (
        type(identity) is not str
        or sha256(canonical_bytes(dict(manifest))).hexdigest() != identity
        or set(manifest)
        != {"artifact_hashes", "callable_identity", "protocol", "schema"}
        or manifest.get("schema") != "job_implementation_evidence.v1"
    ):
        raise EvidenceValidationError(f"{label} implementation is invalid")
    return identity


def scientific_protocol_successor_inventory(
    *,
    current_job_spec: Mapping[str, Any],
    proposed_job_spec: Mapping[str, Any],
    current_executable_manifest: Mapping[str, Any],
    proposed_executable_manifest: Mapping[str, Any],
    current_implementation_manifest: Mapping[str, Any],
    proposed_implementation_manifest: Mapping[str, Any],
    support_hashes: Mapping[str, str],
) -> dict[str, Any]:
    """Derive the exact two-axis reason an in-place retry is forbidden."""

    current_subject = _subject(current_job_spec, label="current Job")
    proposed_subject = _subject(proposed_job_spec, label="proposed Job")
    if (
        current_subject != _executable_identity(current_executable_manifest)
        or proposed_subject != _executable_identity(proposed_executable_manifest)
        or current_subject == proposed_subject
    ):
        raise EvidenceValidationError(
            "scientific protocol successor Executable identity is invalid"
        )
    current_implementation = _implementation(
        current_job_spec,
        current_implementation_manifest,
        label="current Job",
    )
    proposed_implementation = _implementation(
        proposed_job_spec,
        proposed_implementation_manifest,
        label="proposed Job",
    )
    if (
        current_implementation == proposed_implementation
        or current_implementation_manifest.get("callable_identity")
        != proposed_implementation_manifest.get("callable_identity")
        or current_implementation_manifest.get("protocol")
        != proposed_implementation_manifest.get("protocol")
        or current_job_spec.get("callable_identity")
        != proposed_job_spec.get("callable_identity")
        or current_job_spec.get("callable_identity")
        != current_implementation_manifest.get("callable_identity")
    ):
        raise EvidenceValidationError(
            "scientific protocol successor changed its callable contract"
        )
    current_science = current_job_spec.get("scientific_binding")
    proposed_science = proposed_job_spec.get("scientific_binding")
    current_inputs = current_job_spec.get("input_hashes")
    proposed_inputs = proposed_job_spec.get("input_hashes")
    if (
        not isinstance(current_science, Mapping)
        or not isinstance(proposed_science, Mapping)
        or current_science.get("validator_id")
        != proposed_science.get("validator_id")
        or current_science.get("validation_plan_hash")
        == proposed_science.get("validation_plan_hash")
        or not isinstance(current_inputs, list)
        or not isinstance(proposed_inputs, list)
        or current_inputs == proposed_inputs
        or current_inputs != sorted(set(current_inputs))
        or proposed_inputs != sorted(set(proposed_inputs))
    ):
        raise EvidenceValidationError(
            "scientific protocol successor did not change protected inputs"
        )
    required_support = {
        "current_executable_manifest",
        "current_implementation_manifest",
        "current_job_spec",
        "proposed_executable_manifest",
        "proposed_implementation_manifest",
        "proposed_job_spec",
    }
    if set(support_hashes) != required_support:
        raise EvidenceValidationError(
            "scientific protocol successor support inventory is incomplete"
        )
    input_support = sorted(
        {
            support_hashes["current_job_spec"],
            support_hashes["proposed_job_spec"],
        }
    )
    semantic_support = sorted(set(support_hashes.values()))
    return {
        "axes": [
            {
                "accepted_attempt_record_ids": [],
                "axis_id": "immutable-job-input-authority",
                "changed_dimension": "input",
                "state": "infeasible",
                "support_evidence_hashes": input_support,
                "value_assessment": None,
            },
            {
                "accepted_attempt_record_ids": [],
                "axis_id": "protected-scientific-protocol",
                "changed_dimension": "scientific_semantics",
                "state": "semantic_conflict",
                "support_evidence_hashes": semantic_support,
                "value_assessment": None,
            },
        ],
        "coverage_complete": True,
        "no_identity_preserving_repair_route_remaining": True,
        "schema": "engineering_repair_inventory_facts.v1",
    }


class ScientificProtocolSuccessorRepairInventoryValidator:
    """Prove that an exact fix requires a new scientific Job identity."""

    validator_id = SCIENTIFIC_PROTOCOL_REPAIR_INVENTORY_VALIDATOR_ID
    domains = frozenset({"engineering"})
    implementation_path = _THIS_IMPLEMENTATION
    dependency_paths = SCIENTIFIC_PROTOCOL_REPAIR_INVENTORY_DEPENDENCIES
    protocol = SCIENTIFIC_PROTOCOL_REPAIR_INVENTORY_PROTOCOL
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
                "scientific protocol Repair inventory is unauthorized"
            )
        by_name = {
            artifact.output_name: artifact for artifact in request.artifacts
        }
        if len(by_name) != len(request.artifacts) or set(by_name) != _ROLE_NAMES:
            raise EvidenceValidationError(
                "scientific protocol Repair artifacts are incomplete"
            )
        plan = _document(
            by_name["validation_plan"].read_bytes(),
            label="scientific protocol Repair plan",
        )
        binding = _plain(request.binding)
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
            or set(binding) != _BINDING_FIELDS
            or binding.get("schema") != BINDING_SCHEMA
            or binding.get("protocol") != self.protocol
            or binding.get("verification_kind") != "inventory"
            or binding.get("mission_id") != request.mission_id
            or binding.get("artifact_roles") != expected_roles
            or not isinstance(context, Mapping)
            or set(context) != _CONTEXT_FIELDS
            or context.get("schema")
            != "engineering_repair_inventory_context.v1"
            or context.get("scientific_semantics_changed") is not False
            or context.get("repair_attempts") != []
            or context.get("repair_validation_observations") != []
            or context.get("repair_validation_observation_head") is not None
            or context.get("accepted_attempt_head_record_id") is not None
            or set(plan) != _PLAN_FIELDS
            or plan.get("schema") != PLAN_SCHEMA
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
                "scientific protocol Repair plan or context is invalid"
            )
        reproduction = context.get("reproduction_evidence_hashes")
        if reproduction != [by_name["reproduction:0000"].sha256]:
            raise EvidenceValidationError(
                "scientific protocol Repair reproduction binding is invalid"
            )
        documents = {
            name: _document(by_name[name].read_bytes(), label=name)
            for name in (
                "current_executable_manifest",
                "current_implementation_manifest",
                "current_job_spec",
                "proposed_executable_manifest",
                "proposed_implementation_manifest",
                "proposed_job_spec",
            )
        }
        support_hashes = {
            name: by_name[name].sha256 for name in documents
        }
        expected_inventory = scientific_protocol_successor_inventory(
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
        result = _document(
            by_name["validation_result"].read_bytes(),
            label="scientific protocol Repair inventory",
        )
        if result != expected_inventory:
            raise EvidenceValidationError(
                "scientific protocol Repair inventory was not recomputed"
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
        result_manifest = _plain(request.result_manifest)
        if result_manifest != {
            "protocol": self.protocol,
            "result_artifact_hashes": list(opened_hashes),
            "schema": "engineering_repair_validation_dispatch.v1",
            "verification_kind": "inventory",
        }:
            raise EvidenceValidationError(
                "scientific protocol Repair dispatch is invalid"
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
    "SCIENTIFIC_PROTOCOL_REPAIR_INVENTORY_DEPENDENCIES",
    "SCIENTIFIC_PROTOCOL_REPAIR_INVENTORY_PROTOCOL",
    "SCIENTIFIC_PROTOCOL_REPAIR_INVENTORY_VALIDATOR_ID",
    "ScientificProtocolSuccessorRepairInventoryValidator",
    "scientific_protocol_successor_inventory",
]
