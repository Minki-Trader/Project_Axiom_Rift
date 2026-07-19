"""Production engineering validation for the STU-0124 status Repair."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

import axiom_rift.operations.prospective_pair_status_repair_equivalence as equivalence_module
import axiom_rift.operations.repair_validation as repair_validation_module
from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.operations.prospective_pair_status_repair_equivalence import (
    require_prospective_pair_status_correction_verification_claim,
)
from axiom_rift.operations.repair_validation import BINDING_SCHEMA, PLAN_SCHEMA
from axiom_rift.operations.validation import (
    EngineeringRepairValidationRequest,
    EvidenceValidationError,
    ValidatedEvidence,
    validator_identity,
    validator_implementation_sha256,
)


PROSPECTIVE_PAIR_STATUS_REPAIR_ATTEMPT_PROTOCOL = (
    "prospective_pair_status_correction_repair_candidate.v1"
)
_THIS_IMPLEMENTATION = Path(__file__).resolve()
PROSPECTIVE_PAIR_STATUS_REPAIR_ATTEMPT_VALIDATOR_DEPENDENCIES = tuple(
    sorted(
        {
            Path(equivalence_module.__file__).resolve(),
            Path(repair_validation_module.__file__).resolve(),
            *equivalence_module.PROSPECTIVE_PAIR_STATUS_CORRECTION_VALIDATOR_DEPENDENCIES,
        },
        key=lambda path: path.as_posix(),
    )
)
PROSPECTIVE_PAIR_STATUS_REPAIR_ATTEMPT_VALIDATOR_ID = validator_identity(
    protocol=PROSPECTIVE_PAIR_STATUS_REPAIR_ATTEMPT_PROTOCOL,
    domains=frozenset({"engineering"}),
    implementation_sha256=validator_implementation_sha256(
        implementation_path=_THIS_IMPLEMENTATION,
        dependency_paths=(
            PROSPECTIVE_PAIR_STATUS_REPAIR_ATTEMPT_VALIDATOR_DEPENDENCIES
        ),
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
_CANDIDATE_CONTEXT_FIELDS = {
    "bound_validation_observations",
    "cause_hash",
    "changed_dimension",
    "explanation",
    "implementation_proof_hash",
    "job_hash",
    "job_id",
    "new_basis_hash",
    "new_evidence_hashes",
    "previous_basis_hash",
    "prior_attempt_record_id",
    "prior_validation_observation_head",
    "repair_axis_id",
    "repair_id",
    "reproduction_evidence_hashes",
    "resume_action",
    "schema",
    "scientific_semantics_changed",
}
_INNER_PROOF_FIELDS = {
    "changed_dimension",
    "explanation",
    "job_hash",
    "job_id",
    "new_evidence_hashes",
    "new_implementation_identity",
    "previous_implementation_identity",
    "repair_id",
    "reproduction_evidence_hashes",
    "schema",
    "semantic_equivalence_measurement_artifact_hashes",
    "semantic_equivalence_result_manifest_hash",
    "semantic_equivalence_validation_plan_hash",
    "semantic_equivalence_validator_id",
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


def _sorted_digests(
    label: str,
    value: object,
    *,
    allow_empty: bool,
) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or value != sorted(set(value))
    ):
        raise EvidenceValidationError(
            f"{label} must be a sorted unique digest list"
        )
    return tuple(_digest(label, identity) for identity in value)


class ProspectivePairStatusRepairAttemptValidator:
    """Recompute the exact status correction before closing its Repair."""

    validator_id = PROSPECTIVE_PAIR_STATUS_REPAIR_ATTEMPT_VALIDATOR_ID
    domains = frozenset({"engineering"})
    implementation_path = _THIS_IMPLEMENTATION
    dependency_paths = PROSPECTIVE_PAIR_STATUS_REPAIR_ATTEMPT_VALIDATOR_DEPENDENCIES
    protocol = PROSPECTIVE_PAIR_STATUS_REPAIR_ATTEMPT_PROTOCOL
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
                "prospective-pair status Repair request is unauthorized"
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
                "implementation_proof",
                "new_implementation_manifest",
                "validation_plan",
                "validation_result",
                *reproduction_names,
            }
            or not reproduction_names
            or reproduction_names
            != [
                f"reproduction:{ordinal:04d}"
                for ordinal in range(len(reproduction_names))
            ]
        ):
            raise EvidenceValidationError(
                "prospective-pair status Repair artifacts are incomplete"
            )
        plan_artifact = by_name["validation_plan"]
        result_artifact = by_name["validation_result"]
        implementation_proof_artifact = by_name["implementation_proof"]
        new_manifest_artifact = by_name["new_implementation_manifest"]
        plan = _document(
            plan_artifact.read_bytes(),
            label="prospective-pair status Repair validation plan",
        )
        result_content = result_artifact.read_bytes()
        result = _document(
            result_content,
            label="prospective-pair status Repair validation result",
        )
        binding = _plain(request.binding)
        context = None if not isinstance(binding, dict) else binding.get("context")
        expected_roles = [
            {"output_name": name, "sha256": artifact.sha256}
            for name, artifact in sorted(by_name.items())
            if name != "validation_plan"
        ]
        if (
            not isinstance(binding, dict)
            or set(binding) != _BINDING_FIELDS
            or binding.get("schema") != BINDING_SCHEMA
            or binding.get("protocol") != self.protocol
            or binding.get("verification_kind") != "candidate"
            or binding.get("mission_id") != request.mission_id
            or binding.get("artifact_roles") != expected_roles
            or not isinstance(context, dict)
            or set(context) != _CANDIDATE_CONTEXT_FIELDS
            or dict(request.evidence_subject)
            != {"kind": "Repair", "id": request.repair_id}
        ):
            raise EvidenceValidationError(
                "prospective-pair status Repair binding is invalid"
            )
        if (
            set(plan) != _PLAN_FIELDS
            or plan.get("schema") != PLAN_SCHEMA
            or plan.get("validator_id") != self.validator_id
            or plan.get("protocol") != self.protocol
            or plan.get("verification_kind") != "candidate"
            or plan.get("artifact_roles") != expected_roles
            or plan.get("binding_sha256")
            != sha256(canonical_bytes(binding)).hexdigest()
            or request.validation_plan_hash != plan_artifact.sha256
        ):
            raise EvidenceValidationError(
                "prospective-pair status Repair plan differs from its request"
            )
        result_manifest = _plain(request.result_manifest)
        declared_result_hashes = tuple(
            sorted(
                artifact.sha256
                for name, artifact in by_name.items()
                if name != "validation_plan"
            )
        )
        if result_manifest != {
            "protocol": self.protocol,
            "result_artifact_hashes": list(declared_result_hashes),
            "schema": "engineering_repair_validation_dispatch.v1",
            "verification_kind": "candidate",
        }:
            raise EvidenceValidationError(
                "prospective-pair status Repair dispatch is invalid"
            )
        new_evidence = _sorted_digests(
            "prospective-pair status Repair changed evidence",
            context.get("new_evidence_hashes"),
            allow_empty=False,
        )
        reproduction = _sorted_digests(
            "prospective-pair status Repair reproduction evidence",
            context.get("reproduction_evidence_hashes"),
            allow_empty=False,
        )
        new_basis = _digest(
            "prospective-pair status Repair new basis",
            context.get("new_basis_hash"),
        )
        previous_basis = _digest(
            "prospective-pair status Repair previous basis",
            context.get("previous_basis_hash"),
        )
        implementation_proof = _digest(
            "prospective-pair status Repair implementation proof",
            context.get("implementation_proof_hash"),
        )
        bound_observations = context.get("bound_validation_observations")
        observation_head = context.get("prior_validation_observation_head")
        observation_information: set[str] = set()
        if not isinstance(bound_observations, list):
            raise EvidenceValidationError(
                "prospective-pair status Repair observation inventory is invalid"
            )
        for observation in bound_observations:
            if (
                not isinstance(observation, Mapping)
                or set(observation)
                != {
                    "new_information_evidence_hashes",
                    "observation_record_id",
                }
                or type(observation.get("observation_record_id")) is not str
                or not isinstance(
                    observation.get("new_information_evidence_hashes"), list
                )
                or not observation["new_information_evidence_hashes"]
            ):
                raise EvidenceValidationError(
                    "prospective-pair status Repair observation is invalid"
                )
            _digest("Repair observation record", observation["observation_record_id"])
            for identity in observation["new_information_evidence_hashes"]:
                observation_information.add(
                    _digest("Repair observation information", identity)
                )
        if bound_observations:
            if (
                not isinstance(observation_head, Mapping)
                or set(observation_head)
                != {"fingerprint", "record_id", "sequence"}
                or type(observation_head.get("sequence")) is not int
                or observation_head.get("sequence") != len(bound_observations)
                or observation_head.get("record_id")
                != bound_observations[-1]["observation_record_id"]
            ):
                raise EvidenceValidationError(
                    "prospective-pair status Repair observation head is invalid"
                )
            _digest("Repair observation head", observation_head.get("fingerprint"))
        elif observation_head is not None:
            raise EvidenceValidationError(
                "prospective-pair status Repair observation head is unexpected"
            )
        if (
            context.get("job_id") != request.job_id
            or context.get("job_hash") != request.job_hash
            or context.get("repair_id") != request.repair_id
            or context.get("repair_axis_id") != "implementation-source-closure"
            or context.get("changed_dimension") != "implementation"
            or context.get("schema") != "running_job_repair_candidate.v3"
            or type(context.get("explanation")) is not str
            or not context["explanation"]
            or not context["explanation"].isascii()
            or context.get("scientific_semantics_changed") is not False
            or new_basis == previous_basis
            or new_basis not in new_evidence
            or implementation_proof not in new_evidence
            or not observation_information.issubset(new_evidence)
            or set(new_evidence).intersection(reproduction)
            or implementation_proof_artifact.sha256 != implementation_proof
            or new_manifest_artifact.sha256 != new_basis
            or [by_name[name].sha256 for name in reproduction_names]
            != list(reproduction)
        ):
            raise EvidenceValidationError(
                "prospective-pair status Repair context is invalid"
            )
        inner = _document(
            implementation_proof_artifact.read_bytes(),
            label="prospective-pair status Repair implementation proof",
        )
        new_manifest = _document(
            new_manifest_artifact.read_bytes(),
            label="prospective-pair status Repair implementation manifest",
        )
        inner_new_evidence = inner.get("new_evidence_hashes")
        inner_reproduction = inner.get("reproduction_evidence_hashes")
        manifest_artifacts = new_manifest.get("artifact_hashes")
        if (
            set(inner) != _INNER_PROOF_FIELDS
            or inner.get("schema") != "running_job_implementation_repair.v2"
            or inner.get("changed_dimension") != "implementation"
            or inner.get("job_id") != request.job_id
            or inner.get("job_hash") != request.job_hash
            or inner.get("repair_id") != request.repair_id
            or inner.get("explanation") != context.get("explanation")
            or inner.get("new_implementation_identity") != new_basis
            or inner_reproduction != list(reproduction)
            or not isinstance(inner_new_evidence, list)
            or inner_new_evidence != sorted(set(inner_new_evidence))
            or sorted({implementation_proof, *inner_new_evidence})
            != list(new_evidence)
            or set(new_manifest)
            != {"artifact_hashes", "callable_identity", "protocol", "schema"}
            or new_manifest.get("schema") != "job_implementation_evidence.v1"
            or sha256(canonical_bytes(new_manifest)).hexdigest() != new_basis
            or not isinstance(manifest_artifacts, list)
            or manifest_artifacts != sorted(set(manifest_artifacts))
            or not set(manifest_artifacts).issubset(inner_new_evidence)
        ):
            raise EvidenceValidationError(
                "prospective-pair status Repair proof is invalid"
            )
        for name in reproduction_names:
            by_name[name].read_bytes()
        observed = require_prospective_pair_status_correction_verification_claim(
            result_content,
            new_implementation_identity=new_basis,
        )
        if observed != result:
            raise EvidenceValidationError(
                "prospective-pair status Repair result was not recomputed"
            )
        facts = {
            "binding": binding,
            "cause_resolved": True,
            "failure_reproduced": False,
            "material_change": True,
            "mode": "repaired",
            "new_failure_manifest_hash": None,
            "reason_code": None,
        }
        return ValidatedEvidence(
            verdict="passed",
            measurement_artifact_hashes=declared_result_hashes,
            artifact_roles=tuple(
                sorted(
                    (name, artifact.sha256)
                    for name, artifact in by_name.items()
                )
            ),
            facts=facts,
            scientific_eligible=False,
            candidate_eligible=False,
            release_eligible=False,
        )


__all__ = [
    "PROSPECTIVE_PAIR_STATUS_REPAIR_ATTEMPT_PROTOCOL",
    "PROSPECTIVE_PAIR_STATUS_REPAIR_ATTEMPT_VALIDATOR_DEPENDENCIES",
    "PROSPECTIVE_PAIR_STATUS_REPAIR_ATTEMPT_VALIDATOR_ID",
    "ProspectivePairStatusRepairAttemptValidator",
]
