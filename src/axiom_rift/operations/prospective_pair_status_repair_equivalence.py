"""Protocol-specific equivalence proof for STU-0124 trace-status encoding."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

import axiom_rift.operations.repair_semantic_equivalence as semantic_module
from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.operations.repair_semantic_equivalence import (
    SEMANTIC_EQUIVALENCE_BINDING_SCHEMA,
    SEMANTIC_EQUIVALENCE_MEASUREMENT_SCHEMA,
    SEMANTIC_EQUIVALENCE_PLAN_SCHEMA,
    SEMANTIC_EQUIVALENCE_RESULT_SCHEMA,
    RepairSemanticEquivalenceError,
    build_semantic_equivalence_binding,
)
from axiom_rift.operations.validation import (
    EvidenceValidationError,
    EvidenceValidationRequest,
    ValidatedEvidence,
    validator_identity,
    validator_implementation_sha256,
)
from axiom_rift.research.sleeve_exposure_cap_risk_trace import (
    _intent_observation,
)


PROSPECTIVE_PAIR_STATUS_CORRECTION_PROTOCOL = (
    "prospective_pair_status_encoding_correction_equivalence.v1"
)
PROSPECTIVE_PAIR_STATUS_CORRECTION_METHOD = (
    "prospective_pair_status_encoding_conformance.v1"
)
PROSPECTIVE_PAIR_STATUS_CORRECTION_FACTS_SCHEMA = (
    "prospective_pair_status_encoding_correction_facts.v1"
)
PROSPECTIVE_PAIR_STATUS_CORRECTION_VERIFICATION_SCHEMA = (
    "prospective_pair_status_encoding_correction_verification.v1"
)
TRACE_RELATIVE_PATH = "axiom_rift/research/sleeve_exposure_cap_risk_trace.py"
OLD_TRACE_SHA256 = "6d3109c5ad6230d6cc2dcc71c0a393c168bedf01e4fa2f274697d5dc15cd512a"
NEW_TRACE_SHA256 = "d21ad03596d7aa8b85eae0de59bee15c9f5412d70dada83ebdd19297dc614b8c"
OLD_IMPLEMENTATION_IDENTITY = (
    "66c5cea4ceec5fb07ef008f911d41d9f880a795c3abd838a7ab1846d95cd5dac"
)
NEW_IMPLEMENTATION_IDENTITY = (
    "6dff42a7988bba45d6ad5f0fedf6c9a3dbb0ff72c7b70fd1b295f66b243a2b5a"
)
SOURCE_STATUS = "gross_exposure_cap_blocked"
TRACE_STATUS = "risk_policy_skipped"

_THIS_IMPLEMENTATION = Path(__file__).resolve()
_TRACE_IMPLEMENTATION = (
    _THIS_IMPLEMENTATION.parents[1]
    / "research"
    / "sleeve_exposure_cap_risk_trace.py"
)
PROSPECTIVE_PAIR_STATUS_CORRECTION_VALIDATOR_DEPENDENCIES = tuple(
    sorted(
        {
            Path(semantic_module.__file__).resolve(),
            _TRACE_IMPLEMENTATION,
        },
        key=lambda path: path.as_posix(),
    )
)
PROSPECTIVE_PAIR_STATUS_CORRECTION_VALIDATOR_ID = validator_identity(
    protocol=PROSPECTIVE_PAIR_STATUS_CORRECTION_PROTOCOL,
    domains=frozenset({"scientific"}),
    implementation_sha256=validator_implementation_sha256(
        implementation_path=_THIS_IMPLEMENTATION,
        dependency_paths=(
            PROSPECTIVE_PAIR_STATUS_CORRECTION_VALIDATOR_DEPENDENCIES
        ),
    ),
)


def _plain(value: object) -> Any:
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


def prospective_pair_status_correction_measurement(
    *,
    validation_plan_hash: str,
    relative_path: str,
    old_artifact_hash: str,
    new_artifact_hash: str,
) -> dict[str, Any]:
    measurement = semantic_module.semantic_equivalence_measurement(
        validation_plan_hash=validation_plan_hash,
        relative_path=relative_path,
        old_artifact_hash=old_artifact_hash,
        new_artifact_hash=new_artifact_hash,
    )
    measurement["method"] = PROSPECTIVE_PAIR_STATUS_CORRECTION_METHOD
    return measurement


def prospective_pair_status_correction_verification_claim_manifest(
    *, new_implementation_identity: str
) -> dict[str, Any]:
    if new_implementation_identity != NEW_IMPLEMENTATION_IDENTITY:
        raise EvidenceValidationError(
            "prospective-pair status correction implementation is unexpected"
        )
    source = _TRACE_IMPLEMENTATION.read_bytes()
    if sha256(source).hexdigest() != NEW_TRACE_SHA256:
        raise EvidenceValidationError(
            "prospective-pair status correction source drifted"
        )
    observation = _intent_observation(
        (
            "router",
            "2024-01-02T09:00:00",
            "2024-01-02T09:05:00",
            "2024-01-02T09:10:00",
            1,
            SOURCE_STATUS,
        ),
        configuration_id="verification-control",
        executable_id="executable:" + "0" * 64,
        fold_id="fold-verification",
    )
    if observation.get("status") != TRACE_STATUS:
        raise EvidenceValidationError(
            "prospective-pair status correction did not normalize the trace"
        )
    return {
        "new_implementation_identity": NEW_IMPLEMENTATION_IDENTITY,
        "new_trace_sha256": NEW_TRACE_SHA256,
        "old_implementation_identity": OLD_IMPLEMENTATION_IDENTITY,
        "old_trace_sha256": OLD_TRACE_SHA256,
        "protocol": PROSPECTIVE_PAIR_STATUS_CORRECTION_PROTOCOL,
        "schema": PROSPECTIVE_PAIR_STATUS_CORRECTION_VERIFICATION_SCHEMA,
        "source_status": SOURCE_STATUS,
        "trace_relative_path": TRACE_RELATIVE_PATH,
        "trace_status": TRACE_STATUS,
        "validator_id": PROSPECTIVE_PAIR_STATUS_CORRECTION_VALIDATOR_ID,
        "verdict": "passed",
    }


def require_prospective_pair_status_correction_verification_claim(
    content: bytes,
    *,
    new_implementation_identity: str,
) -> dict[str, Any]:
    observed = _document(
        content,
        label="prospective-pair status correction verification",
    )
    expected = prospective_pair_status_correction_verification_claim_manifest(
        new_implementation_identity=new_implementation_identity
    )
    if observed != expected:
        raise EvidenceValidationError(
            "prospective-pair status correction verification is invalid"
        )
    return observed


def require_passed_prospective_pair_status_correction_facts(
    *,
    binding: Mapping[str, Any],
    facts: Mapping[str, Any],
) -> None:
    expected_pair = {
        "new_artifact_hash": NEW_TRACE_SHA256,
        "old_artifact_hash": OLD_TRACE_SHA256,
        "relative_path": TRACE_RELATIVE_PATH,
    }
    if (
        binding.get("schema") != SEMANTIC_EQUIVALENCE_BINDING_SCHEMA
        or binding.get("validator_id")
        != PROSPECTIVE_PAIR_STATUS_CORRECTION_VALIDATOR_ID
        or binding.get("old_implementation_identity")
        != OLD_IMPLEMENTATION_IDENTITY
        or binding.get("new_implementation_identity")
        != NEW_IMPLEMENTATION_IDENTITY
        or binding.get("changed_source_pair_bindings") != [expected_pair]
        or facts
        != {
            "changed_source_pair": expected_pair,
            "covered_surface_ids": list(binding.get("claims", ())),
            "new_implementation_identity": NEW_IMPLEMENTATION_IDENTITY,
            "old_implementation_identity": OLD_IMPLEMENTATION_IDENTITY,
            "repair_id": binding.get("repair_id"),
            "result_manifest_hash": binding.get("result_manifest_hash"),
            "schema": PROSPECTIVE_PAIR_STATUS_CORRECTION_FACTS_SCHEMA,
            "source_status": SOURCE_STATUS,
            "trace_status": TRACE_STATUS,
            "validation_plan_hash": binding.get("validation_plan_hash"),
        }
    ):
        raise RepairSemanticEquivalenceError(
            "prospective-pair status correction facts are invalid"
        )


class ProspectivePairStatusCorrectionEquivalenceValidator:
    """Prove that the only source delta is the exact trace-status adapter."""

    validator_id = PROSPECTIVE_PAIR_STATUS_CORRECTION_VALIDATOR_ID
    domains = frozenset({"scientific"})
    implementation_path = _THIS_IMPLEMENTATION
    dependency_paths = PROSPECTIVE_PAIR_STATUS_CORRECTION_VALIDATOR_DEPENDENCIES
    protocol = PROSPECTIVE_PAIR_STATUS_CORRECTION_PROTOCOL

    def validate(self, request: EvidenceValidationRequest) -> ValidatedEvidence:
        if (
            request.domain != "scientific"
            or request.engineering_fixture
            or request.validator_id != self.validator_id
        ):
            raise EvidenceValidationError(
                "prospective-pair status correction request is unauthorized"
            )
        binding = _plain(request.binding)
        artifacts = {artifact.sha256: artifact for artifact in request.artifacts}
        if (
            not isinstance(binding, dict)
            or binding.get("schema") != SEMANTIC_EQUIVALENCE_BINDING_SCHEMA
            or binding.get("validator_id") != self.validator_id
            or binding.get("validation_plan_hash")
            != request.validation_plan_hash
            or len(artifacts) != len(request.artifacts)
            or set(binding.get("declared_artifact_hashes", ())) != set(artifacts)
        ):
            raise EvidenceValidationError(
                "prospective-pair status correction binding is invalid"
            )
        opened = {
            identity: artifact.read_bytes()
            for identity, artifact in artifacts.items()
        }
        plan = _document(
            opened[request.validation_plan_hash],
            label="prospective-pair status correction plan",
        )
        result_hash = binding.get("result_manifest_hash")
        if type(result_hash) is not str or result_hash not in opened:
            raise EvidenceValidationError(
                "prospective-pair status correction result is absent"
            )
        result = _document(
            opened[result_hash],
            label="prospective-pair status correction result",
        )
        if result != _plain(request.result_manifest):
            raise EvidenceValidationError(
                "prospective-pair status correction result request drifted"
            )
        expected_binding = build_semantic_equivalence_binding(
            plan=plan,
            validation_plan_hash=request.validation_plan_hash,
            result_manifest_hash=result_hash,
            measurement_artifact_hashes=tuple(
                binding.get("measurement_artifact_hashes", ())
            ),
        )
        if binding != expected_binding:
            raise EvidenceValidationError(
                "prospective-pair status correction binding is not exact"
            )
        if (
            plan.get("schema") != SEMANTIC_EQUIVALENCE_PLAN_SCHEMA
            or plan.get("protocol") != self.protocol
            or plan.get("validator_id") != self.validator_id
            or plan.get("job_id") != request.job_id
            or plan.get("job_hash") != request.job_hash
            or plan.get("executable_id")
            != request.evidence_subject.get("id")
            or request.evidence_subject.get("kind") != "Executable"
            or plan.get("old_implementation_identity")
            != OLD_IMPLEMENTATION_IDENTITY
            or plan.get("new_implementation_identity")
            != NEW_IMPLEMENTATION_IDENTITY
        ):
            raise EvidenceValidationError(
                "prospective-pair status correction plan is invalid"
            )
        old_manifest = _document(
            opened[OLD_IMPLEMENTATION_IDENTITY],
            label="old implementation manifest",
        )
        new_manifest = _document(
            opened[NEW_IMPLEMENTATION_IDENTITY],
            label="new implementation manifest",
        )
        if (
            sha256(canonical_bytes(old_manifest)).hexdigest()
            != OLD_IMPLEMENTATION_IDENTITY
            or sha256(canonical_bytes(new_manifest)).hexdigest()
            != NEW_IMPLEMENTATION_IDENTITY
            or old_manifest.get("callable_identity")
            != new_manifest.get("callable_identity")
            or old_manifest.get("protocol") != new_manifest.get("protocol")
        ):
            raise EvidenceValidationError(
                "prospective-pair status correction implementation drifted"
            )
        try:
            old_closure, old_paths, old_non_source = semantic_module._source_closure(
                implementation_manifest=old_manifest,
                opened=opened,
                label="old",
            )
            new_closure, new_paths, new_non_source = semantic_module._source_closure(
                implementation_manifest=new_manifest,
                opened=opened,
                label="new",
            )
            path_bindings, changed_pairs, inventory_hash = (
                semantic_module._source_path_comparison(
                    old_paths=old_paths,
                    new_paths=new_paths,
                )
            )
        except RepairSemanticEquivalenceError as exc:
            raise EvidenceValidationError(
                "prospective-pair status correction closure is invalid"
            ) from exc
        expected_pair = {
            "new_artifact_hash": NEW_TRACE_SHA256,
            "old_artifact_hash": OLD_TRACE_SHA256,
            "relative_path": TRACE_RELATIVE_PATH,
        }
        if (
            old_non_source != new_non_source
            or changed_pairs != [expected_pair]
            or opened.get(OLD_TRACE_SHA256) is None
            or opened.get(NEW_TRACE_SHA256) is None
            or sha256(opened[OLD_TRACE_SHA256]).hexdigest() != OLD_TRACE_SHA256
            or sha256(opened[NEW_TRACE_SHA256]).hexdigest() != NEW_TRACE_SHA256
            or plan.get("changed_source_pair_bindings") != changed_pairs
            or plan.get("old_source_closure_hash") != old_closure
            or plan.get("new_source_closure_hash") != new_closure
            or plan.get("source_path_inventory_hash") != inventory_hash
        ):
            raise EvidenceValidationError(
                "prospective-pair status correction changes another source surface"
            )
        measurements = binding.get("measurement_artifact_hashes")
        if not isinstance(measurements, list) or len(measurements) != 1:
            raise EvidenceValidationError(
                "prospective-pair status correction measurement is absent"
            )
        measurement = _document(
            opened[measurements[0]],
            label="prospective-pair status correction measurement",
        )
        if measurement != {
            "method": PROSPECTIVE_PAIR_STATUS_CORRECTION_METHOD,
            **expected_pair,
            "schema": SEMANTIC_EQUIVALENCE_MEASUREMENT_SCHEMA,
            "validation_plan_hash": request.validation_plan_hash,
        }:
            raise EvidenceValidationError(
                "prospective-pair status correction measurement is invalid"
            )
        claims = plan.get("claims")
        if not isinstance(claims, list) or claims != sorted(set(claims)):
            raise EvidenceValidationError(
                "prospective-pair status correction claims are invalid"
            )
        expected_result = {
            "executable_id": plan["executable_id"],
            "job_hash": request.job_hash,
            "job_id": request.job_id,
            "measurement_artifact_hashes": measurements,
            "new_implementation_identity": NEW_IMPLEMENTATION_IDENTITY,
            "old_implementation_identity": OLD_IMPLEMENTATION_IDENTITY,
            "repair_id": plan["repair_id"],
            "schema": SEMANTIC_EQUIVALENCE_RESULT_SCHEMA,
            "surface_results": [
                {"surface_id": claim, "verdict": "passed"}
                for claim in claims
            ],
            "validation_plan_hash": request.validation_plan_hash,
            "verdict": "passed",
        }
        if result != expected_result:
            raise EvidenceValidationError(
                "prospective-pair status correction result is not reproducible"
            )
        facts = {
            "changed_source_pair": expected_pair,
            "covered_surface_ids": claims,
            "new_implementation_identity": NEW_IMPLEMENTATION_IDENTITY,
            "old_implementation_identity": OLD_IMPLEMENTATION_IDENTITY,
            "repair_id": plan["repair_id"],
            "result_manifest_hash": result_hash,
            "schema": PROSPECTIVE_PAIR_STATUS_CORRECTION_FACTS_SCHEMA,
            "source_status": SOURCE_STATUS,
            "trace_status": TRACE_STATUS,
            "validation_plan_hash": request.validation_plan_hash,
        }
        require_passed_prospective_pair_status_correction_facts(
            binding=binding,
            facts=facts,
        )
        return ValidatedEvidence(
            verdict="passed",
            claims=tuple(claims),
            measurement_artifact_hashes=tuple(measurements),
            facts=facts,
            scientific_eligible=False,
            candidate_eligible=False,
            release_eligible=False,
        )


__all__ = [
    "NEW_IMPLEMENTATION_IDENTITY",
    "PROSPECTIVE_PAIR_STATUS_CORRECTION_METHOD",
    "PROSPECTIVE_PAIR_STATUS_CORRECTION_PROTOCOL",
    "PROSPECTIVE_PAIR_STATUS_CORRECTION_VALIDATOR_DEPENDENCIES",
    "PROSPECTIVE_PAIR_STATUS_CORRECTION_VALIDATOR_ID",
    "ProspectivePairStatusCorrectionEquivalenceValidator",
    "prospective_pair_status_correction_measurement",
    "prospective_pair_status_correction_verification_claim_manifest",
    "require_passed_prospective_pair_status_correction_facts",
    "require_prospective_pair_status_correction_verification_claim",
]
