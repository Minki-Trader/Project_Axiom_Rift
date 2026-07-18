"""Protocol-specific proof for fixed-hold authority-projection Repairs.

This validator is intentionally separate from the running Job source closure.
It opens the exact old and new closure bytes, permits only the bounded
authority and Repair-harness symbol inventory, binds the new artifacts to the
registered local implementation, and independently exercises the correction
route and its fail-closed parser boundaries.  Scientific surfaces remain the
Writer-derived immutable inventory; this protocol grants no scientific,
candidate, holdout, or Release eligibility.
"""

from __future__ import annotations

import ast
from hashlib import sha256
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Any, Mapping

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.validation import (
    EvidenceValidationError,
    EvidenceValidationRequest,
    ValidatedEvidence,
    validator_identity,
    validator_implementation_sha256,
)


# These literals and structural rules intentionally do not import the producer
# in ``repair_semantic_equivalence``.  A protocol-specific validator must not
# let the implementation being repaired redefine the packet that proves it.
SEMANTIC_EQUIVALENCE_PLAN_SCHEMA = (
    "implementation_repair_semantic_equivalence_plan.v2"
)
SEMANTIC_EQUIVALENCE_BINDING_SCHEMA = (
    "implementation_repair_semantic_equivalence_binding.v2"
)
SEMANTIC_EQUIVALENCE_MEASUREMENT_SCHEMA = (
    "implementation_repair_semantic_equivalence_measurement.v3"
)
SEMANTIC_EQUIVALENCE_RESULT_SCHEMA = (
    "implementation_repair_semantic_equivalence_result.v1"
)
FIXED_HOLD_AUTHORITY_CORRECTION_PROTOCOL = (
    "fixed_hold_replay_authority_correction_equivalence.v1"
)
FIXED_HOLD_AUTHORITY_CORRECTION_METHOD = (
    "fixed_hold_replay_authority_projection_conformance.v1"
)
FIXED_HOLD_AUTHORITY_CORRECTION_FACTS_SCHEMA = (
    "fixed_hold_replay_authority_correction_equivalence_facts.v1"
)
FIXED_HOLD_AUTHORITY_CORRECTION_CASE_IDS = (
    "cross_event_family_authority_rejected",
    "exact_resume_ancestry_stream_4_5_6_7_8",
    "noncanonical_v2_manifest_inventory_rejected",
    "resume_authority_tampering_rejected",
    "resume_payload_roundtrip_is_exact",
    "same_event_family_authority_exact",
    "zero_delta_transition_payloads_exact",
)
_SURFACE_CATEGORIES = frozenset(
    {
        "callable",
        "claim",
        "component",
        "cost",
        "decision",
        "external",
        "lifecycle",
        "protocol",
        "runtime",
        "scientific",
        "source",
    }
)
_IMPLEMENTATION_MANIFEST_FIELDS = {
    "artifact_hashes",
    "callable_identity",
    "protocol",
    "schema",
}
_SOURCE_CLOSURE_FIELDS = {"callable_identity", "dependencies", "schema"}
_SOURCE_CLOSURE_ENTRY_FIELDS = {"path", "sha256"}
_SOURCE_CLOSURE_SCHEMA = "job_implementation_source_closure.v1"
_PLAN_FIELDS = {
    "changed_source_pair_bindings",
    "claims",
    "executable_id",
    "job_hash",
    "job_id",
    "new_implementation_artifact_hashes",
    "new_implementation_identity",
    "new_source_closure_hash",
    "old_implementation_artifact_hashes",
    "old_implementation_identity",
    "old_source_closure_hash",
    "protocol",
    "repair_id",
    "schema",
    "surface_inventory",
    "surface_inventory_hash",
    "source_path_inventory_hash",
    "validator_id",
}
_BINDING_FIELDS = {
    "changed_source_pair_bindings",
    "claims",
    "declared_artifact_hashes",
    "executable_id",
    "measurement_artifact_hashes",
    "new_implementation_artifact_hashes",
    "new_implementation_identity",
    "new_source_closure_hash",
    "old_implementation_artifact_hashes",
    "old_implementation_identity",
    "old_source_closure_hash",
    "repair_id",
    "result_manifest_hash",
    "schema",
    "surface_inventory_hash",
    "source_path_inventory_hash",
    "validation_plan_hash",
    "validator_id",
}
_MEASUREMENT_FIELDS = {
    "method",
    "new_artifact_hash",
    "old_artifact_hash",
    "relative_path",
    "schema",
    "validation_plan_hash",
}
_RESULT_FIELDS = {
    "executable_id",
    "job_hash",
    "job_id",
    "measurement_artifact_hashes",
    "new_implementation_identity",
    "old_implementation_identity",
    "repair_id",
    "schema",
    "surface_results",
    "validation_plan_hash",
    "verdict",
}
_FIXED_HOLD_FACT_FIELDS = {
    "added_artifact_hashes",
    "artifact_equivalence_method",
    "authority_deltas",
    "changed_source_pair_results",
    "conformance_case_ids",
    "covered_surface_ids",
    "new_implementation_artifact_hashes",
    "new_implementation_identity",
    "new_source_closure_hash",
    "old_implementation_artifact_hashes",
    "old_implementation_identity",
    "old_source_closure_hash",
    "pairing_status",
    "removed_artifact_hashes",
    "repair_id",
    "result_manifest_hash",
    "schema",
    "surface_inventory_hash",
    "source_path_bindings",
    "source_path_inventory_hash",
    "unchanged_artifact_hashes",
    "validation_plan_hash",
    "validation_protocol",
    "validator_id",
}


def _plain(value: object) -> Any:
    def thaw(item: object) -> Any:
        if isinstance(item, Mapping):
            return {str(key): thaw(child) for key, child in item.items()}
        if isinstance(item, (list, tuple)):
            return [thaw(child) for child in item]
        return item

    return parse_canonical(canonical_bytes(thaw(value)))


def _canonical_document(content: bytes, *, label: str) -> dict[str, Any]:
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


def _digest_list(label: str, value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise EvidenceValidationError(f"{label} must be a non-empty digest list")
    normalized = tuple(value)
    if normalized != tuple(sorted(set(normalized))):
        raise EvidenceValidationError(f"{label} must be sorted and unique")
    return tuple(_digest(label, item) for item in normalized)


def _relative_source_path(label: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise EvidenceValidationError(f"{label} is not non-empty ASCII")
    candidate = PurePosixPath(value)
    if (
        candidate.is_absolute()
        or "\\" in value
        or candidate.as_posix() != value
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise EvidenceValidationError(f"{label} is not a normalized relative path")
    return value


def _artifact_partition(
    *,
    old_artifact_hashes: object,
    new_artifact_hashes: object,
) -> tuple[
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    old_artifacts = _digest_list("old implementation artifacts", old_artifact_hashes)
    new_artifacts = _digest_list("new implementation artifacts", new_artifact_hashes)
    old_set = set(old_artifacts)
    new_set = set(new_artifacts)
    return (
        old_artifacts,
        new_artifacts,
        tuple(sorted(old_set & new_set)),
        tuple(sorted(old_set - new_set)),
        tuple(sorted(new_set - old_set)),
    )


def _source_closure(
    *,
    implementation_manifest: Mapping[str, Any],
    opened: Mapping[str, bytes],
    label: str,
) -> tuple[str, dict[str, str], tuple[str, ...]]:
    artifacts = _digest_list(
        f"{label} implementation artifacts",
        implementation_manifest.get("artifact_hashes"),
    )
    candidates: list[tuple[str, dict[str, Any]]] = []
    for identity in artifacts:
        content = opened.get(identity)
        if type(content) is not bytes or sha256(content).hexdigest() != identity:
            raise EvidenceValidationError(
                f"{label} implementation artifact bytes are invalid"
            )
        try:
            value = parse_canonical(content)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict) and value.get("schema") == _SOURCE_CLOSURE_SCHEMA:
            candidates.append((identity, value))
    if len(candidates) != 1:
        raise EvidenceValidationError(
            f"{label} implementation source closure is ambiguous"
        )
    closure_hash, closure = candidates[0]
    dependencies = closure.get("dependencies")
    if (
        set(closure) != _SOURCE_CLOSURE_FIELDS
        or closure.get("callable_identity")
        != implementation_manifest.get("callable_identity")
        or not isinstance(dependencies, list)
        or not dependencies
    ):
        raise EvidenceValidationError(f"{label} source closure is invalid")
    path_hashes: dict[str, str] = {}
    ordered_paths: list[str] = []
    for dependency in dependencies:
        if (
            not isinstance(dependency, Mapping)
            or set(dependency) != _SOURCE_CLOSURE_ENTRY_FIELDS
        ):
            raise EvidenceValidationError(
                f"{label} source closure dependency is invalid"
            )
        relative_path = _relative_source_path(
            f"{label} source closure path", dependency.get("path")
        )
        identity = _digest(
            f"{label} source closure artifact", dependency.get("sha256")
        )
        if relative_path in path_hashes or identity not in opened:
            raise EvidenceValidationError(
                f"{label} source closure dependency is unavailable or duplicated"
            )
        path_hashes[relative_path] = identity
        ordered_paths.append(relative_path)
    source_artifacts = {closure_hash, *path_hashes.values()}
    if (
        ordered_paths != sorted(ordered_paths)
        or closure_hash in path_hashes.values()
        or not source_artifacts.issubset(artifacts)
    ):
        raise EvidenceValidationError(
            f"{label} source closure does not explain its artifacts"
        )
    return (
        closure_hash,
        path_hashes,
        tuple(sorted(set(artifacts) - source_artifacts)),
    )


def _source_path_comparison(
    *,
    old_paths: Mapping[str, str],
    new_paths: Mapping[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, str]], str]:
    if set(old_paths) != set(new_paths) or not old_paths:
        raise EvidenceValidationError(
            "old/new source closures do not preserve one path inventory"
        )
    bindings = [
        {
            "changed": old_paths[path] != new_paths[path],
            "new_artifact_hash": new_paths[path],
            "old_artifact_hash": old_paths[path],
            "relative_path": path,
        }
        for path in sorted(old_paths)
    ]
    changed = [
        {
            "new_artifact_hash": item["new_artifact_hash"],
            "old_artifact_hash": item["old_artifact_hash"],
            "relative_path": item["relative_path"],
        }
        for item in bindings
        if item["changed"]
    ]
    inventory_hash = canonical_digest(
        domain="implementation-repair-source-path-inventory",
        payload={"relative_paths": sorted(old_paths)},
    )
    return bindings, changed, inventory_hash


_THIS_IMPLEMENTATION = Path(__file__).resolve()
_SOURCE_ROOT = _THIS_IMPLEMENTATION.parents[2]
_REQUIRED_CHANGED_PATHS = (
    "axiom_rift/operations/repair_semantic_equivalence.py",
    "axiom_rift/operations/running_job.py",
    "axiom_rift/operations/running_job_context.py",
    "axiom_rift/operations/validation.py",
    "axiom_rift/research/fixed_hold_replay_runtime.py",
    "axiom_rift/research/replay_obligation.py",
    "axiom_rift/research/replay_satisfaction_invalidation.py",
)
_FIXED_HOLD_JOB_SOURCE_PATHS = (
    "axiom_rift/__init__.py",
    "axiom_rift/core/__init__.py",
    "axiom_rift/core/canonical.py",
    "axiom_rift/core/component_surface.py",
    "axiom_rift/core/identity.py",
    "axiom_rift/operations/__init__.py",
    "axiom_rift/operations/completion_evidence_scope.py",
    "axiom_rift/operations/completion_validity_projection.py",
    "axiom_rift/operations/permits.py",
    "axiom_rift/operations/recorded_transition_authority.py",
    "axiom_rift/operations/repair_semantic_equivalence.py",
    "axiom_rift/operations/running_job.py",
    "axiom_rift/operations/running_job_context.py",
    "axiom_rift/operations/scientific_history.py",
    "axiom_rift/operations/validation.py",
    "axiom_rift/operations/validation_integrity.py",
    "axiom_rift/research/__init__.py",
    "axiom_rift/research/adjudication.py",
    "axiom_rift/research/audit_integrity_proof.py",
    "axiom_rift/research/chassis.py",
    "axiom_rift/research/completed_period_atomic_trace.py",
    "axiom_rift/research/data.py",
    "axiom_rift/research/discovery.py",
    "axiom_rift/research/effective_evidence_scope.py",
    "axiom_rift/research/evidence_proofs.py",
    "axiom_rift/research/fixed_hold_family_job.py",
    "axiom_rift/research/fixed_hold_family_trace.py",
    "axiom_rift/research/fixed_hold_historical_projection.py",
    "axiom_rift/research/fixed_hold_replay_runtime.py",
    "axiom_rift/research/fixed_hold_shared_trace.py",
    "axiom_rift/research/fixed_hold_trace_engine.py",
    "axiom_rift/research/governance.py",
    "axiom_rift/research/historical_adjudication.py",
    "axiom_rift/research/historical_family_binding.py",
    "axiom_rift/research/historical_scientific_validity.py",
    "axiom_rift/research/historical_semantic_transition.py",
    "axiom_rift/research/replay_coverage.py",
    "axiom_rift/research/replay_exposure.py",
    "axiom_rift/research/replay_obligation.py",
    "axiom_rift/research/replay_satisfaction_invalidation.py",
    "axiom_rift/research/reproducible_cache.py",
    "axiom_rift/research/scientific_trace.py",
    "axiom_rift/research/selection_inference.py",
    "axiom_rift/research/semantic_question.py",
    "axiom_rift/research/trials.py",
    "axiom_rift/research/validation_v2.py",
    "axiom_rift/research/volatility_duration_fixed_hold.py",
    "axiom_rift/research/volatility_duration_fixed_hold_job.py",
    "axiom_rift/storage/__init__.py",
    "axiom_rift/storage/atomic_file.py",
    "axiom_rift/storage/control_next_action.py",
    "axiom_rift/storage/evidence.py",
    "axiom_rift/storage/index.py",
    "axiom_rift/storage/journal.py",
    "axiom_rift/storage/path_boundary.py",
    "axiom_rift/storage/state.py",
)
FIXED_HOLD_AUTHORITY_CORRECTION_OLD_IMPLEMENTATION_IDENTITY = (
    "921d179ecc580391d144db48ea31d8ef45ddbf5a3330c689e77c9bf55bbdcdc9"
)
FIXED_HOLD_AUTHORITY_CORRECTION_NEW_IMPLEMENTATION_IDENTITY = (
    "7b86dbaf0f6e2e3bf48ba86b80e55eba54d870a2e6f9f5493c931bfd8c8ca730"
)
FIXED_HOLD_DIRECT_ORIGIN_CORRECTION_OLD_IMPLEMENTATION_IDENTITY = (
    "71ab6a637226a7e7468a7422937f49b6f64c1fb0db03b1b38db24fb0e182f7c1"
)
FIXED_HOLD_DIRECT_ORIGIN_CORRECTION_NEW_IMPLEMENTATION_IDENTITY = (
    "8c0f4121fdfd0419566258d142cd6272ee8dc80144371adf72e1586c89ebfb8b"
)
FIXED_HOLD_SCIENTIFIC_CHANGE_RETURN_OLD_IMPLEMENTATION_IDENTITY = (
    "45efe133cce1450d2057d8bb01393efd24051f31de8137f0ce75ed614580aa81"
)
FIXED_HOLD_SCIENTIFIC_CHANGE_RETURN_NEW_IMPLEMENTATION_IDENTITY = (
    "18b8145685a60593e64045a0225ba315b318a534ef18d8b21658960b42247bdd"
)
FIXED_HOLD_COST_AWARE_CROSS_STUDY_ORIGIN_OLD_IMPLEMENTATION_IDENTITY = (
    "62bdde524c5c339ac88a553f2d3867f444a5d7a88ded69e6bbfe0d8332b9d4de"
)
FIXED_HOLD_COST_AWARE_CROSS_STUDY_ORIGIN_NEW_IMPLEMENTATION_IDENTITY = (
    "7ec3f8d40bbc7fa064956fda17f59a7cf202e200dd1412e6772c0a83027f1d5c"
)
FIXED_HOLD_AUTHORITY_CORRECTION_VERIFICATION_SCHEMA = (
    "fixed_hold_authority_correction_verification.v1"
)
_VERIFICATION_FIELDS = {
    "authority_deltas",
    "conformance_case_ids",
    "new_implementation_identity",
    "protocol",
    "schema",
    "source_artifacts",
    "validator_id",
    "verdict",
}


def _assignment_names(node: ast.Assign | ast.AnnAssign) -> tuple[str, ...]:
    targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
    names: list[str] = []
    for target in targets:
        if isinstance(target, ast.Name):
            names.append(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            names.extend(
                item.id for item in target.elts if isinstance(item, ast.Name)
            )
    return tuple(sorted(set(names)))


def _definition_inventory(document: bytes) -> dict[str, str]:
    """Return a location-free inventory of module and class definitions."""

    try:
        tree = ast.parse(document)
    except (SyntaxError, TypeError, ValueError) as exc:
        raise EvidenceValidationError(
            "fixed-hold correction source cannot be parsed"
        ) from exc
    inventory: dict[str, str] = {}
    imports: list[str] = []

    def store(key: str, node: ast.AST) -> None:
        if key in inventory:
            raise EvidenceValidationError(
                "fixed-hold correction source symbol inventory is ambiguous"
            )
        inventory[key] = ast.dump(node, include_attributes=False)

    for ordinal, node in enumerate(tree.body):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append(ast.dump(node, include_attributes=False))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            store(f"function:{node.name}", node)
        elif isinstance(node, ast.ClassDef):
            header = ast.ClassDef(
                name=node.name,
                bases=node.bases,
                keywords=node.keywords,
                body=[],
                decorator_list=node.decorator_list,
                type_params=getattr(node, "type_params", []),
            )
            store(f"class:{node.name}:header", header)
            for child_ordinal, child in enumerate(node.body):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    store(f"class:{node.name}.{child.name}", child)
                elif isinstance(child, (ast.Assign, ast.AnnAssign)):
                    names = _assignment_names(child)
                    if names:
                        for name in names:
                            store(f"class:{node.name}:{name}", child)
                    else:
                        store(
                            f"class:{node.name}:statement:{child_ordinal}",
                            child,
                        )
                elif (
                    isinstance(child, ast.Expr)
                    and isinstance(child.value, ast.Constant)
                    and isinstance(child.value.value, str)
                ):
                    store(f"class:{node.name}:docstring", child)
                else:
                    store(
                        f"class:{node.name}:statement:{child_ordinal}", child
                    )
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            names = _assignment_names(node)
            if names:
                for name in names:
                    store(f"module:{name}", node)
            else:
                store(f"module:statement:{ordinal}", node)
        elif (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            store("module:docstring", node)
        else:
            store(f"module:statement:{ordinal}:{type(node).__name__}", node)
    if imports:
        inventory["module:imports"] = "\n".join(sorted(imports))
    return inventory


def changed_source_symbols(old_document: bytes, new_document: bytes) -> tuple[str, ...]:
    """Expose the exact location-free symbol delta for proof and tests."""

    old = _definition_inventory(old_document)
    new = _definition_inventory(new_document)
    return tuple(
        sorted(key for key in set(old).union(new) if old.get(key) != new.get(key))
    )


_ALLOWED_CHANGED_SYMBOLS = {
    "axiom_rift/operations/repair_semantic_equivalence.py": frozenset(
        {
            "function:build_semantic_equivalence_plan",
            "function:fixed_hold_authority_correction_measurement",
            "function:require_passed_fixed_hold_authority_correction_facts",
            "function:require_passed_semantic_equivalence_facts",
            "module:FIXED_HOLD_AUTHORITY_CORRECTION_CASE_IDS",
            "module:FIXED_HOLD_AUTHORITY_CORRECTION_FACTS_SCHEMA",
            "module:FIXED_HOLD_AUTHORITY_CORRECTION_METHOD",
            "module:FIXED_HOLD_AUTHORITY_CORRECTION_PROTOCOL",
            "module:_FIXED_HOLD_FACT_FIELDS",
            "module:_FIXED_HOLD_PAIR_RESULT_FIELDS",
            "module:__all__",
        }
    ),
    "axiom_rift/operations/running_job.py": frozenset(
        {
            "function:effective_running_job_implementation",
            "module:imports",
        }
    ),
    "axiom_rift/operations/running_job_context.py": frozenset(
        {
            "class:RunningJobExecutionContext.project_bound_fixed_hold_replay_context",
            "function:_require_correction_invalidation_route",
            "function:_require_correction_pending_invalidation",
            "function:_require_replay_deferral_transition",
            "function:_require_replay_progress_transition",
            "function:_require_replay_resume_transition",
            "function:_require_same_event_family_authority",
        }
    ),
    "axiom_rift/operations/validation.py": frozenset(
        {"class:EvidenceValidatorRegistry.require_registered_protocol"}
    ),
    "axiom_rift/research/fixed_hold_replay_runtime.py": frozenset(
        {
            "class:FixedHoldRepairContext.plan_fixed_hold_authority_correction_repair",
            "class:FixedHoldRepairContext.resolve_fixed_hold_authority_correction_verification",
            "function:materialize_running_job_implementation_repair_proof",
            "module:imports",
        }
    ),
    "axiom_rift/research/replay_obligation.py": frozenset(
        {
            "function:replay_resume_evidence_from_identity_payload",
            "module:__all__",
        }
    ),
    "axiom_rift/research/replay_satisfaction_invalidation.py": frozenset(
        {
            "class:ReplaySatisfactionInvalidationAuditManifest.from_mapping",
            "class:ReplaySatisfactionInvalidationAuditManifestV2.__post_init__",
            "class:ReplaySatisfactionInvalidationAuditManifestV2.from_mapping",
        }
    ),
}

_DIRECT_ORIGIN_REQUIRED_CHANGED_PATHS = (
    "axiom_rift/operations/running_job_context.py",
)
_DIRECT_ORIGIN_JOB_SOURCE_PATHS = tuple(
    sorted(
        set(_FIXED_HOLD_JOB_SOURCE_PATHS).difference(
            {
                "axiom_rift/research/volatility_duration_fixed_hold.py",
                "axiom_rift/research/volatility_duration_fixed_hold_job.py",
            }
        )
        | {
            "axiom_rift/operations/historical_family_authority_admission.py",
            "axiom_rift/research/evidence_inputs.py",
            "axiom_rift/research/gap_fixed_hold.py",
            "axiom_rift/research/gap_fixed_hold_job.py",
            "axiom_rift/research/historical_study_registry.py",
            "axiom_rift/research/replay_member_assignment.py",
        }
    )
)
_DIRECT_ORIGIN_ALLOWED_CHANGED_SYMBOLS = {
    "axiom_rift/operations/running_job_context.py": frozenset(
        {
            "class:RunningJobExecutionContext.project_bound_fixed_hold_replay_context",
            "function:_replay_execution_origin_record",
            "function:_require_correction_invalidation_route",
            "function:_require_recorded_new_replay_obligation_origin",
            "function:_require_replay_execution_origin_route",
            "function:_unique_ascii_list",
            "module:_NEW_OBLIGATION_RESULT_FIELDS",
            "module:imports",
        }
    ),
}
_SCIENTIFIC_CHANGE_RETURN_JOB_SOURCE_PATHS = tuple(
    sorted(
        set(_DIRECT_ORIGIN_JOB_SOURCE_PATHS).difference(
            {"axiom_rift/research/gap_fixed_hold_job.py"}
        )
        | {
            "axiom_rift/research/gap_event_fixed_hold_v3.py",
            "axiom_rift/research/gap_event_fixed_hold_v3_job.py",
        }
    )
)
_SCIENTIFIC_CHANGE_RETURN_ALLOWED_CHANGED_SYMBOLS = {
    "axiom_rift/operations/running_job_context.py": frozenset(
        {
            "function:_replay_execution_origin_record",
            "function:_require_replay_execution_origin_route",
        }
    ),
}
_COST_AWARE_CROSS_STUDY_ORIGIN_JOB_SOURCE_PATHS = tuple(
    sorted(
        set(_FIXED_HOLD_JOB_SOURCE_PATHS).difference(
            {
                "axiom_rift/research/completed_period_atomic_trace.py",
                "axiom_rift/research/fixed_hold_family_job.py",
                "axiom_rift/research/fixed_hold_family_trace.py",
                "axiom_rift/research/fixed_hold_historical_projection.py",
                "axiom_rift/research/fixed_hold_replay_runtime.py",
                "axiom_rift/research/fixed_hold_shared_trace.py",
                "axiom_rift/research/fixed_hold_trace_engine.py",
                "axiom_rift/research/historical_semantic_transition.py",
                "axiom_rift/research/volatility_duration_fixed_hold.py",
                "axiom_rift/research/volatility_duration_fixed_hold_job.py",
            }
        )
        | {
            "axiom_rift/operations/historical_family_authority_reader.py",
            "axiom_rift/research/cost_aware_execution_pair.py",
            "axiom_rift/research/cost_aware_execution_pair_engine.py",
            "axiom_rift/research/cost_aware_execution_pair_job.py",
            "axiom_rift/research/cost_aware_execution_pair_runtime.py",
            "axiom_rift/research/cost_aware_execution_protocol.py",
            "axiom_rift/research/cost_aware_execution_trace.py",
            "axiom_rift/research/event_label_discovery.py",
            "axiom_rift/research/replay_member_assignment.py",
            "axiom_rift/research/scientific_study.py",
        }
    )
)
_COST_AWARE_CROSS_STUDY_ORIGIN_ALLOWED_CHANGED_SYMBOLS = {
    "axiom_rift/operations/running_job_context.py": frozenset(
        {
            "class:RunningJobExecutionContext."
            "project_bound_fixed_hold_replay_context",
        }
    ),
}
_CORRECTION_PROFILES = {
    FIXED_HOLD_AUTHORITY_CORRECTION_NEW_IMPLEMENTATION_IDENTITY: {
        "allowed_changed_symbols": _ALLOWED_CHANGED_SYMBOLS,
        "old_implementation_identity": (
            FIXED_HOLD_AUTHORITY_CORRECTION_OLD_IMPLEMENTATION_IDENTITY
        ),
        "required_changed_paths": _REQUIRED_CHANGED_PATHS,
        "source_paths": _FIXED_HOLD_JOB_SOURCE_PATHS,
    },
    FIXED_HOLD_DIRECT_ORIGIN_CORRECTION_NEW_IMPLEMENTATION_IDENTITY: {
        "allowed_changed_symbols": _DIRECT_ORIGIN_ALLOWED_CHANGED_SYMBOLS,
        "old_implementation_identity": (
            FIXED_HOLD_DIRECT_ORIGIN_CORRECTION_OLD_IMPLEMENTATION_IDENTITY
        ),
        "required_changed_paths": _DIRECT_ORIGIN_REQUIRED_CHANGED_PATHS,
        "source_paths": _DIRECT_ORIGIN_JOB_SOURCE_PATHS,
    },
    FIXED_HOLD_SCIENTIFIC_CHANGE_RETURN_NEW_IMPLEMENTATION_IDENTITY: {
        "allowed_changed_symbols": (
            _SCIENTIFIC_CHANGE_RETURN_ALLOWED_CHANGED_SYMBOLS
        ),
        "old_implementation_identity": (
            FIXED_HOLD_SCIENTIFIC_CHANGE_RETURN_OLD_IMPLEMENTATION_IDENTITY
        ),
        "required_changed_paths": _DIRECT_ORIGIN_REQUIRED_CHANGED_PATHS,
        "source_paths": _SCIENTIFIC_CHANGE_RETURN_JOB_SOURCE_PATHS,
    },
    FIXED_HOLD_COST_AWARE_CROSS_STUDY_ORIGIN_NEW_IMPLEMENTATION_IDENTITY: {
        "allowed_changed_symbols": (
            _COST_AWARE_CROSS_STUDY_ORIGIN_ALLOWED_CHANGED_SYMBOLS
        ),
        "old_implementation_identity": (
            FIXED_HOLD_COST_AWARE_CROSS_STUDY_ORIGIN_OLD_IMPLEMENTATION_IDENTITY
        ),
        "required_changed_paths": _DIRECT_ORIGIN_REQUIRED_CHANGED_PATHS,
        "source_paths": _COST_AWARE_CROSS_STUDY_ORIGIN_JOB_SOURCE_PATHS,
    },
}


def _correction_profile(
    *,
    new_implementation_identity: object,
    old_implementation_identity: object | None = None,
) -> Mapping[str, Any]:
    """Select one immutable old/new Repair profile without replacing history."""

    if type(new_implementation_identity) is not str or (
        old_implementation_identity is not None
        and type(old_implementation_identity) is not str
    ):
        raise EvidenceValidationError(
            "fixed-hold correction implementation identities are malformed"
        )
    profile = _CORRECTION_PROFILES.get(new_implementation_identity)
    if profile is None or (
        old_implementation_identity is not None
        and old_implementation_identity
        != profile["old_implementation_identity"]
    ):
        raise EvidenceValidationError(
            "fixed-hold implementation pair is not the registered correction"
        )
    return profile


def _transition_records(record: Any, event_kind: str, result: Mapping[str, Any]):
    from axiom_rift.storage.index import IndexRecord

    sequence = record.authority_sequence
    event_id = record.authority_event_id
    offset = record.authority_offset
    operation_id = f"fixed-hold-correction-operation-{sequence:02d}"
    return (
        IndexRecord(
            kind="operation",
            record_id=operation_id,
            subject=record.subject,
            status="success",
            fingerprint=operation_id,
            payload={"event_kind": event_kind, "result": dict(result)},
            authority_sequence=sequence,
            authority_event_id=event_id,
            authority_offset=offset,
        ),
        IndexRecord(
            kind="journal-event",
            record_id=event_id,
            subject=record.subject,
            status=event_kind,
            fingerprint=event_id,
            payload={"operation_id": operation_id},
            event_stream="control",
            event_sequence=sequence,
            authority_sequence=sequence,
            authority_event_id=event_id,
            authority_offset=offset,
        ),
    )


def _exercise_direct_obligation_origin(tamper: str | None) -> None:
    from axiom_rift.operations.running_job_context import (
        RunningJobAuthorityError,
        _require_recorded_new_replay_obligation_origin,
    )
    from axiom_rift.research.historical_adjudication import ReplayPriority
    from axiom_rift.research.replay_obligation import HistoricalReplayObligation
    from axiom_rift.storage.index import IndexRecord, LocalIndex

    mission_id = "MIS-FIXED-HOLD-DIRECT-ORIGIN"
    study_id = "STU-FIXED-HOLD-DIRECT-ORIGIN"
    adjudication_id = "historical-adjudication:" + "1" * 64
    obligation = HistoricalReplayObligation(
        governing_mission_id=mission_id,
        historical_adjudication_id=adjudication_id,
        replay_priority=ReplayPriority.P1,
        original_study_id=study_id,
        original_study_close_record_id="2" * 64,
        original_completion_record_id="3" * 64,
        original_executable_id="executable:" + "4" * 64,
        audit_artifact_hash="5" * 64,
        validation_plan_hash="6" * 64,
        measurement_artifact_hash="7" * 64,
        claim_ids=("claim-direct-origin",),
        criterion_ids=("criterion-direct-origin",),
        reason_codes=("prospective_exact_replay_required",),
    )
    authority = {
        "authority_sequence": 11,
        "authority_event_id": "8" * 64,
        "authority_offset": 800,
    }
    adjudication_payload = {
        "adjudication": {
            "candidate_eligible": False,
            "claims": [{"claim_id": "claim-direct-origin"}],
            "criteria": [{"criterion_id": "criterion-direct-origin"}],
        },
        "audit_artifact_hash": obligation.audit_artifact_hash,
        "candidate_delta": 0,
        "completion_record_id": obligation.original_completion_record_id,
        "disposition": "replay_required",
        "executable_id": obligation.original_executable_id,
        "holdout_delta": 0,
        "measurement_artifact_hash": obligation.measurement_artifact_hash,
        "reason_codes": list(obligation.reason_codes),
        "replay_obligation_authority": (
            "reused_existing" if tamper == "origin" else "derived_new"
        ),
        "replay_obligation_id": obligation.identity,
        "replay_obligation_origin_adjudication_id": adjudication_id,
        "replay_priority": obligation.replay_priority.value,
        "schema": "historical_scientific_adjudication.v2",
        "study_close_record_id": obligation.original_study_close_record_id,
        "study_id": obligation.original_study_id,
        "trial_delta": 0,
        "validation_plan_hash": obligation.validation_plan_hash,
    }
    adjudication = IndexRecord(
        kind="historical-scientific-adjudication",
        record_id=adjudication_id,
        subject=f"Study:{study_id}",
        status="replay_required",
        fingerprint=adjudication_id.removeprefix("historical-adjudication:"),
        payload=adjudication_payload,
        **(
            {**authority, "authority_event_id": "9" * 64}
            if tamper == "cross_event"
            else authority
        ),
    )
    stream = f"historical-replay-obligation:{obligation.identity}"
    initial = IndexRecord(
        kind="historical-replay-obligation",
        record_id=obligation.identity,
        subject=f"Mission:{mission_id}",
        status="pending",
        fingerprint=obligation.identity.removeprefix(
            "historical-replay-obligation:"
        ),
        payload={"obligation": obligation.to_identity_payload()},
        event_stream=stream,
        event_sequence=1,
        **authority,
    )
    result = {
        "adjudication_record_ids": [adjudication_id],
        "audit_artifact_hash": obligation.audit_artifact_hash,
        "candidate_delta": 0,
        "holdout_delta": 0,
        "replay_obligation_ids": [
            (
                "historical-replay-obligation:" + "0" * 64
                if tamper == "result"
                else obligation.identity
            )
        ],
        "replay_priority_escalation_ids": [],
        "reused_replay_obligation_ids": [],
        "trial_delta": 0,
    }
    records = [
        initial,
        adjudication,
        *_transition_records(
            initial,
            "historical_scientific_adjudications_recorded",
            result,
        ),
    ]
    with TemporaryDirectory() as temporary:
        with LocalIndex(Path(temporary) / "direct-origin.sqlite") as index:
            index.put_many(records)
            if tamper is None:
                _require_recorded_new_replay_obligation_origin(
                    index,
                    obligation=obligation,
                    record=initial,
                )
                return
            try:
                _require_recorded_new_replay_obligation_origin(
                    index,
                    obligation=obligation,
                    record=initial,
                )
            except RunningJobAuthorityError:
                return
    raise EvidenceValidationError(
        "fixed-hold correction accepted tampered direct obligation origin"
    )


def _exercise_resume_route(tamper: str | None) -> None:
    from axiom_rift.operations.running_job_context import (
        RunningJobAuthorityError,
        _require_replay_progress_transition,
        _replay_execution_origin_record,
    )
    from axiom_rift.research.replay_obligation import (
        ReplayDeferral,
        ReplayDeferralBasis,
        ReplayDeferralBasisKind,
        ReplayExecutionBinding,
        ReplayResumeCondition,
        ReplayResumeConditionKind,
        ReplayResumeEvidence,
    )
    from axiom_rift.storage.index import IndexRecord, LocalIndex

    obligation_id = "historical-replay-obligation:" + "1" * 64
    mission_id = "MIS-FIXED-HOLD-CORRECTION"

    class Obligation:
        identity = obligation_id
        governing_mission_id = mission_id

    obligation = Obligation()
    stream = f"historical-replay-obligation:{obligation_id}"

    def authority(sequence: int) -> dict[str, Any]:
        return {
            "authority_sequence": sequence,
            "authority_event_id": f"{sequence:064x}",
            "authority_offset": sequence * 100,
        }

    invalidation = IndexRecord(
        kind="historical-replay-satisfaction-invalidation",
        record_id="historical-replay-satisfaction-invalidation:" + "2" * 64,
        subject=f"Mission:{mission_id}",
        status="pending",
        fingerprint="2" * 64,
        payload={"prior_status": "satisfied"},
        event_stream=stream,
        event_sequence=4,
        **authority(4),
    )
    prior_binding = ReplayExecutionBinding(
        obligation_ids=(obligation_id,),
        portfolio_decision_id="decision:" + "3" * 64,
        replay_study_id="STU-PRIOR-CORRECTION",
        replay_executable_id="executable:" + "4" * 64,
    )

    def progress(sequence: int, binding: ReplayExecutionBinding) -> IndexRecord:
        payload = {
            "binding": binding.to_identity_payload(),
            "obligation_id": obligation_id,
            "prior_status": "pending",
        }
        return IndexRecord(
            kind="historical-replay-obligation-progress",
            record_id="historical-replay-progress:"
            + canonical_digest(
                domain="historical-replay-obligation-progress",
                payload=payload,
            ),
            subject=f"Mission:{mission_id}",
            status="in_progress",
            fingerprint=binding.identity,
            payload=payload,
            event_stream=stream,
            event_sequence=sequence,
            **authority(sequence),
        )

    prior_progress = progress(5, prior_binding)
    condition = ReplayResumeCondition(
        kind=ReplayResumeConditionKind.REGISTERED_DEVELOPMENT_MATERIAL,
        protocol_id="python.source.fixture_fixed_hold.v1",
        original_executable_ids=("executable:" + "5" * 64,),
        criterion_ids=("E01-familywise-selection",),
    )
    deferral = ReplayDeferral(
        obligation_id=obligation_id,
        basis=ReplayDeferralBasis(
            kind=ReplayDeferralBasisKind.STUDY_DIAGNOSIS,
            record_id="diagnosis:" + "6" * 64,
            subject_id="STU-PRIOR-CORRECTION",
        ),
        reason_codes=("fixture_engineering_gap",),
        resume_conditions=(condition,),
    )
    deferral_payload = {
        "obligation_id": obligation_id,
        "prior_status": "pending" if tamper == "deferral_prior" else "in_progress",
        "resolution": deferral.to_identity_payload(),
    }
    deferral_record = IndexRecord(
        kind="historical-replay-obligation-resolution",
        record_id=deferral.identity,
        subject=f"Mission:{mission_id}",
        status="deferred",
        fingerprint=deferral.identity.removeprefix(
            "historical-replay-deferral:"
        ),
        payload=deferral_payload,
        event_stream=stream,
        event_sequence=6,
        **authority(6),
    )
    evidence = ReplayResumeEvidence(
        obligation_id=obligation_id,
        deferral_id=(
            "historical-replay-deferral:" + "7" * 64
            if tamper == "resume_deferral"
            else deferral.identity
        ),
        resume_condition_id=condition.identity,
        trigger_record_id="development-material:" + "8" * 64,
    )
    resume_payload = {
        "obligation_id": obligation_id,
        "prior_status": "deferred",
        "resume_evidence": evidence.to_identity_payload(),
        "scientific_claim_delta": 0,
        "scientific_satisfaction_delta": 0,
        "scientific_trial_delta": 0,
    }
    resume_record = IndexRecord(
        kind="historical-replay-obligation-resume",
        record_id=evidence.identity,
        subject=f"Mission:{mission_id}",
        status="pending",
        fingerprint=evidence.identity.removeprefix(
            "historical-replay-resume-evidence:"
        ),
        payload=resume_payload,
        event_stream=stream,
        event_sequence=7,
        **authority(7),
    )
    current_binding = ReplayExecutionBinding(
        obligation_ids=(obligation_id,),
        portfolio_decision_id="decision:" + "9" * 64,
        replay_study_id="STU-CURRENT-CORRECTION",
        replay_executable_id="executable:" + "a" * 64,
    )
    current_progress = progress(8, current_binding)
    deferral_result: dict[str, Any] = {
        "deferred_replay_obligation_ids": [obligation_id]
    }
    resume_result: dict[str, Any] = {
        "resume_condition_ids": [condition.identity],
        "resume_trigger_record_ids": [evidence.trigger_record_id],
        "resumed_replay_obligation_ids": [obligation_id],
        "scientific_claim_delta": 0,
        "scientific_satisfaction_delta": 0,
        "scientific_trial_delta": 0,
    }
    if tamper == "resume_result_extra":
        resume_result["unexpected"] = 0
    prefix = [
        IndexRecord(
            kind=kind,
            record_id=f"fixed-hold-correction-prefix-{sequence}",
            subject=f"Mission:{mission_id}",
            status=status,
            fingerprint=f"fixed-hold-correction-prefix-{sequence}",
            payload={"fixture_prefix": sequence},
            event_stream=stream,
            event_sequence=sequence,
            **authority(sequence),
        )
        for sequence, kind, status in (
            (1, "historical-replay-obligation", "pending"),
            (2, "historical-replay-obligation-progress", "in_progress"),
            (3, "historical-replay-obligation-resolution", "satisfied"),
        )
    ]
    records = [
        *prefix,
        invalidation,
        *_transition_records(
            invalidation,
            "historical_replay_satisfaction_invalidated",
            {
                "candidate_delta": 0,
                "holdout_reveal_delta": 0,
                "scientific_claim_delta": 0,
                "scientific_satisfaction_delta": 0,
                "scientific_trial_delta": 0,
            },
        ),
        prior_progress,
        *_transition_records(prior_progress, "trial_registered", {}),
        deferral_record,
        *_transition_records(
            deferral_record,
            "historical_replay_obligations_deferred",
            deferral_result,
        ),
        resume_record,
        *_transition_records(
            resume_record,
            "historical_replay_obligations_resumed",
            resume_result,
        ),
        current_progress,
        *_transition_records(current_progress, "trial_registered", {}),
    ]
    with TemporaryDirectory() as temporary:
        with LocalIndex(Path(temporary) / "conformance.sqlite") as index:
            index.put_many(records)
            if tamper is None:
                _require_replay_progress_transition(
                    index,
                    obligation=obligation,
                    record=current_progress,
                    require_current_head=True,
                )
                observed = _replay_execution_origin_record(
                    index,
                    obligation=obligation,
                    current_progress=current_progress,
                )
                if observed != invalidation:
                    raise EvidenceValidationError(
                        "fixed-hold correction conformance lost its invalidation"
                    )
                return
            try:
                _replay_execution_origin_record(
                    index,
                    obligation=obligation,
                    current_progress=current_progress,
                )
            except RunningJobAuthorityError:
                return
    raise EvidenceValidationError(
        "fixed-hold correction conformance accepted tampered resume authority"
    )


def _exercise_scientific_change_return_route(tamper: str | None) -> None:
    from axiom_rift.operations.running_job_context import (
        RunningJobAuthorityError,
        _require_replay_execution_origin_route,
    )
    from axiom_rift.storage.index import IndexRecord, LocalIndex

    obligation_id = "historical-replay-obligation:" + "b" * 64
    mission_id = "MIS-FIXED-HOLD-CORRECTION"

    class Obligation:
        identity = obligation_id
        governing_mission_id = mission_id

    obligation = Obligation()
    stream = f"historical-replay-obligation:{obligation_id}"

    def authority(sequence: int) -> dict[str, Any]:
        return {
            "authority_sequence": sequence,
            "authority_event_id": f"{sequence:064x}",
            "authority_offset": sequence * 100,
        }

    prefix = [
        IndexRecord(
            kind=kind,
            record_id=f"scientific-change-return-prefix-{sequence}",
            subject=f"Mission:{mission_id}",
            status=status,
            fingerprint=f"scientific-change-return-prefix-{sequence}",
            payload={"fixture_prefix": sequence},
            event_stream=stream,
            event_sequence=sequence,
            **authority(sequence),
        )
        for sequence, kind, status in (
            (1, "historical-replay-obligation", "pending"),
            (2, "historical-replay-obligation-progress", "in_progress"),
        )
    ]
    return_payload = {
        "candidate_delta": 0,
        "engineering_completion_record_id": "c" * 64,
        "engineering_disposition_hash": "d" * 64,
        "engineering_disposition_record_id": "e" * 64,
        "holdout_reveal_delta": 0,
        "obligation_id": obligation_id,
        "prior_progress_record_id": prefix[-1].record_id,
        "prior_status": "in_progress",
        "replay_executable_id": "executable:" + "f" * 64,
        "replay_study_close_record_id": "1" * 64,
        "replay_study_id": "STU-PREVIOUS-CORRECTION",
        "resume_condition": "admit a corrected successor Study",
        "schema": "historical_replay_scientific_change_return.v1",
        "scientific_claim_delta": 0,
        "scientific_failure_delta": 0,
        "scientific_satisfaction_delta": 0,
        "scientific_trial_delta": 1 if tamper == "zero_delta" else 0,
        "study_diagnosis_id": "diagnosis:" + "2" * 64,
        "successor_scope": "study",
        "terminal_credit_delta": 0,
    }
    return_fingerprint = canonical_digest(
        domain="historical-replay-scientific-change-return",
        payload=return_payload,
    )
    returned = IndexRecord(
        kind="historical-replay-scientific-change-return",
        record_id=(
            "historical-replay-scientific-change-return:"
            + return_fingerprint
        ),
        subject=f"Mission:{mission_id}",
        status="pending",
        fingerprint=return_fingerprint,
        payload=return_payload,
        event_stream=stream,
        event_sequence=3,
        **authority(3),
    )
    result = {
        "candidate_delta": 0,
        "engineering_completion_record_id": return_payload[
            "engineering_completion_record_id"
        ],
        "engineering_disposition_hash": return_payload[
            "engineering_disposition_hash"
        ],
        "engineering_disposition_record_id": return_payload[
            "engineering_disposition_record_id"
        ],
        "holdout_reveal_delta": 0,
        "return_record_ids": [returned.record_id],
        "returned_replay_obligation_ids": [
            (
                "historical-replay-obligation:" + "0" * 64
                if tamper == "result"
                else obligation_id
            )
        ],
        "scientific_claim_delta": 0,
        "scientific_failure_delta": 0,
        "scientific_satisfaction_delta": 0,
        "scientific_trial_delta": 0,
        "study_diagnosis_id": return_payload["study_diagnosis_id"],
        "study_id": return_payload["replay_study_id"],
        "terminal_credit_delta": 0,
    }
    current = IndexRecord(
        kind="historical-replay-obligation-progress",
        record_id="historical-replay-progress:" + "3" * 64,
        subject=f"Mission:{mission_id}",
        status="in_progress",
        fingerprint="3" * 64,
        payload={"obligation_id": obligation_id},
        event_stream=stream,
        event_sequence=4,
        **authority(4),
    )
    event_kind = (
        "historical_replay_obligations_deferred"
        if tamper == "event"
        else "historical_replay_obligations_returned_for_scientific_change"
    )
    records = [
        *prefix,
        returned,
        *_transition_records(returned, event_kind, result),
        current,
    ]
    with TemporaryDirectory() as temporary:
        with LocalIndex(Path(temporary) / "scientific-return.sqlite") as index:
            index.put_many(records)
            if tamper is None:
                _require_replay_execution_origin_route(
                    index,
                    obligation=obligation,
                    current_progress=current,
                    family_record=None,
                )
                return
            try:
                _require_replay_execution_origin_route(
                    index,
                    obligation=obligation,
                    current_progress=current,
                    family_record=None,
                )
            except RunningJobAuthorityError:
                return
    raise EvidenceValidationError(
        "fixed-hold correction accepted tampered scientific-change return"
    )


def _run_correction_conformance() -> tuple[str, ...]:
    from axiom_rift.operations.running_job_context import (
        RunningJobAuthorityError,
        _require_same_event_family_authority,
    )
    from axiom_rift.research.replay_obligation import (
        ReplayObligationError,
        ReplayResumeEvidence,
        replay_resume_evidence_from_identity_payload,
    )
    from axiom_rift.research.replay_satisfaction_invalidation import (
        ReplayCompletionValidityDefect,
        ReplayCompletionValidityDefectCode,
        ReplayCompletionValidityObservation,
        ReplaySatisfactionInvalidationAuditManifestV2,
    )
    from axiom_rift.storage.index import IndexRecord

    passed: set[str] = set()
    _exercise_direct_obligation_origin(None)
    for tamper in ("cross_event", "origin", "result"):
        _exercise_direct_obligation_origin(tamper)
    _exercise_resume_route(None)
    passed.update(
        {
            "exact_resume_ancestry_stream_4_5_6_7_8",
            "zero_delta_transition_payloads_exact",
        }
    )
    for tamper in (
        "deferral_prior",
        "resume_deferral",
        "resume_result_extra",
    ):
        _exercise_resume_route(tamper)
    _exercise_scientific_change_return_route(None)
    for tamper in ("event", "result", "zero_delta"):
        _exercise_scientific_change_return_route(tamper)
    passed.add("resume_authority_tampering_rejected")

    evidence = ReplayResumeEvidence(
        obligation_id="historical-replay-obligation:" + "b" * 64,
        deferral_id="historical-replay-deferral:" + "c" * 64,
        resume_condition_id="historical-replay-resume-condition:" + "d" * 64,
        trigger_record_id="development-material:" + "e" * 64,
    )
    rebuilt = replay_resume_evidence_from_identity_payload(
        evidence.to_identity_payload()
    )
    if rebuilt.identity != evidence.identity:
        raise EvidenceValidationError(
            "fixed-hold correction resume parser changed exact identity"
        )
    forged_resume = evidence.to_identity_payload()
    forged_resume["unexpected"] = 0
    try:
        replay_resume_evidence_from_identity_payload(forged_resume)
    except ReplayObligationError:
        pass
    else:
        raise EvidenceValidationError(
            "fixed-hold correction resume parser accepted an extra field"
        )
    passed.add("resume_payload_roundtrip_is_exact")

    observations = tuple(
        ReplayCompletionValidityObservation(
            completion_record_id=character * 64,
            executable_id="executable:" + executable_character * 64,
            invalidation_record_id=(
                "historical-scientific-validity-invalidation:"
                + invalidation_character * 64
            ),
            reason="invalid historical completion authority",
            affected_criterion_ids=("E01-familywise-selection",),
            validity_stream_sequence=1,
            authority_event_id=event_character * 64,
            authority_sequence=ordinal,
            authority_offset=ordinal * 100,
        )
        for ordinal, (
            character,
            executable_character,
            invalidation_character,
            event_character,
        ) in enumerate((('1', '3', '5', '7'), ('2', '4', '6', '8')), start=1)
    )
    validity = ReplayCompletionValidityDefect(
        code=(
            ReplayCompletionValidityDefectCode
            .EVIDENCE_COMPLETION_VALIDITY_INVALID
        ),
        observations=observations,
    )
    manifest = ReplaySatisfactionInvalidationAuditManifestV2(
        governing_mission_id="MIS-FIXED-HOLD-CORRECTION",
        obligation_id="historical-replay-obligation:" + "9" * 64,
        satisfaction_record_id=(
            "historical-replay-satisfaction:" + "a" * 64
        ),
        satisfaction_event_sequence=2,
        portfolio_decision_id="decision:" + "b" * 64,
        replay_study_id="STU-FIXED-HOLD-CORRECTION",
        replay_executable_id=observations[0].executable_id,
        replay_study_close_record_id="c" * 64,
        study_diagnosis_id="diagnosis:" + "d" * 64,
        completion_record_ids=tuple(
            item.completion_record_id for item in observations
        ),
        defects=(validity,),
    )
    noncanonical = manifest.to_identity_payload()
    noncanonical["completion_record_ids"] = list(
        reversed(noncanonical["completion_record_ids"])
    )
    try:
        ReplaySatisfactionInvalidationAuditManifestV2.from_mapping(
            noncanonical
        )
    except ValueError:
        pass
    else:
        raise EvidenceValidationError(
            "fixed-hold correction manifest parser accepted noncanonical order"
        )
    passed.add("noncanonical_v2_manifest_inventory_rejected")

    family = IndexRecord(
        kind="historical-family-authority",
        record_id="historical-family-authority:" + "e" * 64,
        subject="Mission:MIS-FIXED-HOLD-CORRECTION",
        status="active",
        fingerprint="e" * 64,
        payload={},
        authority_sequence=11,
        authority_event_id="f" * 64,
        authority_offset=1100,
    )
    authority = (11, "f" * 64, 1100)
    _require_same_event_family_authority(
        family_record=family,
        invalidation_authority=authority,
        family_authority_id=family.record_id,
    )
    passed.add("same_event_family_authority_exact")
    try:
        _require_same_event_family_authority(
            family_record=family,
            invalidation_authority=(12, "f" * 64, 1100),
            family_authority_id=family.record_id,
        )
    except RunningJobAuthorityError:
        pass
    else:
        raise EvidenceValidationError(
            "fixed-hold correction accepted cross-event family authority"
        )
    passed.add("cross_event_family_authority_rejected")
    observed = tuple(sorted(passed))
    if observed != FIXED_HOLD_AUTHORITY_CORRECTION_CASE_IDS:
        raise EvidenceValidationError(
            "fixed-hold correction conformance coverage is incomplete"
        )
    return observed


FIXED_HOLD_AUTHORITY_CORRECTION_VALIDATOR_DEPENDENCIES = tuple(
    sorted(
        {
            _SOURCE_ROOT / path
            for profile in _CORRECTION_PROFILES.values()
            for path in profile["source_paths"]
        }
        | {
            _SOURCE_ROOT / "axiom_rift/core/canonical.py",
            _SOURCE_ROOT / "axiom_rift/core/identity.py",
            _SOURCE_ROOT / "axiom_rift/operations/recorded_transition_authority.py",
            _SOURCE_ROOT / "axiom_rift/storage/index.py",
        },
        key=lambda path: path.as_posix(),
    )
)
FIXED_HOLD_AUTHORITY_CORRECTION_VALIDATOR_ID = validator_identity(
    protocol=FIXED_HOLD_AUTHORITY_CORRECTION_PROTOCOL,
    domains=frozenset({"scientific"}),
    implementation_sha256=validator_implementation_sha256(
        implementation_path=_THIS_IMPLEMENTATION,
        dependency_paths=(
            FIXED_HOLD_AUTHORITY_CORRECTION_VALIDATOR_DEPENDENCIES
        ),
    ),
)


def fixed_hold_authority_correction_verification_manifest(
    *,
    new_implementation_identity: str,
) -> dict[str, Any]:
    """Recompute one typed engineering verification outside the Job closure."""

    profile = _correction_profile(
        new_implementation_identity=new_implementation_identity,
    )
    conformance = _run_correction_conformance()
    source_artifacts = [
        {
            "relative_path": relative_path,
            "sha256": sha256((_SOURCE_ROOT / relative_path).read_bytes()).hexdigest(),
        }
        for relative_path in profile["required_changed_paths"]
    ]
    return {
        "authority_deltas": {
            "candidate": 0,
            "holdout_reveal": 0,
            "scientific_claim": 0,
            "scientific_satisfaction": 0,
            "scientific_trial": 0,
        },
        "conformance_case_ids": list(conformance),
        "new_implementation_identity": new_implementation_identity,
        "protocol": FIXED_HOLD_AUTHORITY_CORRECTION_PROTOCOL,
        "schema": FIXED_HOLD_AUTHORITY_CORRECTION_VERIFICATION_SCHEMA,
        "source_artifacts": source_artifacts,
        "validator_id": FIXED_HOLD_AUTHORITY_CORRECTION_VALIDATOR_ID,
        "verdict": "passed",
    }


def require_fixed_hold_authority_correction_verification(
    content: bytes,
    *,
    new_implementation_identity: str,
) -> dict[str, Any]:
    """Reject caller-authored verification that cannot be recomputed exactly."""

    try:
        observed = parse_canonical(content)
    except (TypeError, ValueError) as exc:
        raise EvidenceValidationError(
            "fixed-hold correction verification is not canonical"
        ) from exc
    expected = fixed_hold_authority_correction_verification_manifest(
        new_implementation_identity=new_implementation_identity,
    )
    if (
        not isinstance(observed, dict)
        or set(observed) != _VERIFICATION_FIELDS
        or observed != expected
    ):
        raise EvidenceValidationError(
            "fixed-hold correction verification is not independently reproducible"
        )
    return observed


class FixedHoldAuthorityCorrectionEquivalenceValidator:
    """Recompute the bounded authority correction from exact source bytes."""

    validator_id = FIXED_HOLD_AUTHORITY_CORRECTION_VALIDATOR_ID
    domains = frozenset({"scientific"})
    implementation_path = _THIS_IMPLEMENTATION
    dependency_paths = FIXED_HOLD_AUTHORITY_CORRECTION_VALIDATOR_DEPENDENCIES
    protocol = FIXED_HOLD_AUTHORITY_CORRECTION_PROTOCOL

    def validate(self, request: EvidenceValidationRequest) -> ValidatedEvidence:
        if (
            request.domain != "scientific"
            or request.engineering_fixture
            or request.validator_id != self.validator_id
        ):
            raise EvidenceValidationError(
                "fixed-hold correction validation request is unauthorized"
            )
        binding = _plain(request.binding)
        subject = request.evidence_subject
        if (
            not isinstance(binding, dict)
            or set(binding) != _BINDING_FIELDS
            or binding.get("schema") != SEMANTIC_EQUIVALENCE_BINDING_SCHEMA
            or binding.get("validator_id") != self.validator_id
            or binding.get("validation_plan_hash")
            != request.validation_plan_hash
            or not isinstance(subject, Mapping)
            or subject.get("kind") != "Executable"
            or binding.get("executable_id") != subject.get("id")
        ):
            raise EvidenceValidationError(
                "fixed-hold correction binding is invalid"
            )
        artifacts = {artifact.sha256: artifact for artifact in request.artifacts}
        declared = binding.get("declared_artifact_hashes")
        if (
            len(artifacts) != len(request.artifacts)
            or not isinstance(declared, list)
            or declared != sorted(set(declared))
            or set(declared) != set(artifacts)
        ):
            raise EvidenceValidationError(
                "fixed-hold correction artifact set is not exact"
            )
        opened = {
            identity: artifact.read_bytes()
            for identity, artifact in artifacts.items()
        }
        plan = _canonical_document(
            opened[request.validation_plan_hash],
            label="fixed-hold correction validation plan",
        )
        result_hash = binding.get("result_manifest_hash")
        if type(result_hash) is not str or result_hash not in opened:
            raise EvidenceValidationError(
                "fixed-hold correction result artifact is absent"
            )
        result = _canonical_document(
            opened[result_hash], label="fixed-hold correction result"
        )
        if result != _plain(request.result_manifest):
            raise EvidenceValidationError(
                "fixed-hold correction result differs from its artifact"
            )
        if (
            set(plan) != _PLAN_FIELDS
            or plan.get("schema") != SEMANTIC_EQUIVALENCE_PLAN_SCHEMA
            or plan.get("protocol") != self.protocol
            or plan.get("validator_id") != self.validator_id
            or plan.get("job_id") != request.job_id
            or plan.get("job_hash") != request.job_hash
            or plan.get("executable_id") != subject.get("id")
            or plan.get("executable_id") != binding.get("executable_id")
            or plan.get("repair_id") != binding.get("repair_id")
            or plan.get("surface_inventory_hash")
            != binding.get("surface_inventory_hash")
            or plan.get("source_path_inventory_hash")
            != binding.get("source_path_inventory_hash")
            or plan.get("old_source_closure_hash")
            != binding.get("old_source_closure_hash")
            or plan.get("new_source_closure_hash")
            != binding.get("new_source_closure_hash")
            or plan.get("changed_source_pair_bindings")
            != binding.get("changed_source_pair_bindings")
            or plan.get("claims") != binding.get("claims")
        ):
            raise EvidenceValidationError(
                "fixed-hold correction plan differs from its request"
            )
        inventory = plan.get("surface_inventory")
        claims = plan.get("claims")
        if (
            not isinstance(inventory, list)
            or not inventory
            or not isinstance(claims, list)
            or claims != sorted(set(claims))
            or claims
            != sorted(
                item.get("surface_id")
                for item in inventory
                if isinstance(item, Mapping)
            )
            or canonical_digest(
                domain="implementation-repair-semantic-surface-inventory",
                payload={"surface_inventory": inventory},
            )
            != plan.get("surface_inventory_hash")
        ):
            raise EvidenceValidationError(
                "fixed-hold correction semantic inventory is invalid"
            )
        if inventory != sorted(
            inventory,
            key=lambda item: (
                item.get("category", "") if isinstance(item, Mapping) else "",
                item.get("path", "") if isinstance(item, Mapping) else "",
                item.get("surface_id", "") if isinstance(item, Mapping) else "",
            ),
        ):
            raise EvidenceValidationError(
                "fixed-hold correction semantic inventory is not canonical"
            )
        for item in inventory:
            if (
                not isinstance(item, dict)
                or set(item) != {"category", "path", "surface_id", "value_hash"}
                or item.get("category") not in _SURFACE_CATEGORIES
                or type(item.get("path")) is not str
                or not item["path"]
                or not item["path"].isascii()
            ):
                raise EvidenceValidationError(
                    "fixed-hold correction semantic surface entry is invalid"
                )
            value_hash = _digest(
                "fixed-hold semantic surface value", item.get("value_hash")
            )
            expected_surface_id = "repair-surface:" + canonical_digest(
                domain="implementation-repair-semantic-surface",
                payload={
                    "category": item["category"],
                    "path": item["path"],
                    "value_hash": value_hash,
                },
            )
            if item.get("surface_id") != expected_surface_id:
                raise EvidenceValidationError(
                    "fixed-hold correction semantic surface identity is invalid"
                )
        if len({item["path"] for item in inventory}) != len(inventory):
            raise EvidenceValidationError(
                "fixed-hold correction semantic surface path is ambiguous"
            )

        old_identity = binding.get("old_implementation_identity")
        new_identity = binding.get("new_implementation_identity")
        profile = _correction_profile(
            new_implementation_identity=new_identity,
            old_implementation_identity=old_identity,
        )
        if (
            type(old_identity) is not str
            or type(new_identity) is not str
            or old_identity not in opened
            or new_identity not in opened
            or old_identity == new_identity
            or plan.get("old_implementation_identity") != old_identity
            or plan.get("new_implementation_identity") != new_identity
        ):
            raise EvidenceValidationError(
                "fixed-hold correction old/new identity binding is invalid"
            )
        old_manifest = _canonical_document(
            opened[old_identity], label="old fixed-hold implementation manifest"
        )
        new_manifest = _canonical_document(
            opened[new_identity], label="new fixed-hold implementation manifest"
        )
        for manifest, identity, artifact_field in (
            (old_manifest, old_identity, "old_implementation_artifact_hashes"),
            (new_manifest, new_identity, "new_implementation_artifact_hashes"),
        ):
            if (
                set(manifest) != _IMPLEMENTATION_MANIFEST_FIELDS
                or manifest.get("schema") != "job_implementation_evidence.v1"
                or sha256(canonical_bytes(manifest)).hexdigest() != identity
                or manifest.get("artifact_hashes") != binding.get(artifact_field)
                or manifest.get("artifact_hashes") != plan.get(artifact_field)
                or any(
                    artifact_hash not in opened
                    for artifact_hash in manifest.get("artifact_hashes", ())
                )
            ):
                raise EvidenceValidationError(
                    "fixed-hold correction implementation manifest is invalid"
                )
        if (
            old_manifest.get("callable_identity")
            != new_manifest.get("callable_identity")
            or old_manifest.get("protocol") != new_manifest.get("protocol")
            or not str(old_manifest.get("protocol", "")).startswith(
                "python.source."
            )
        ):
            raise EvidenceValidationError(
                "fixed-hold correction changes callable or protocol semantics"
            )
        try:
            (
                old_artifacts,
                new_artifacts,
                unchanged_artifacts,
                removed_artifacts,
                added_artifacts,
            ) = _artifact_partition(
                old_artifact_hashes=old_manifest.get("artifact_hashes"),
                new_artifact_hashes=new_manifest.get("artifact_hashes"),
            )
            old_closure, old_paths, old_non_source = _source_closure(
                implementation_manifest=old_manifest,
                opened=opened,
                label="old",
            )
            new_closure, new_paths, new_non_source = _source_closure(
                implementation_manifest=new_manifest,
                opened=opened,
                label="new",
            )
            source_bindings, changed_pairs, source_inventory_hash = (
                _source_path_comparison(old_paths=old_paths, new_paths=new_paths)
            )
        except Exception as exc:
            raise EvidenceValidationError(
                "fixed-hold correction source closure is invalid"
            ) from exc
        if (
            old_non_source != new_non_source
            or old_closure != plan.get("old_source_closure_hash")
            or old_closure != binding.get("old_source_closure_hash")
            or new_closure != plan.get("new_source_closure_hash")
            or new_closure != binding.get("new_source_closure_hash")
            or source_inventory_hash
            != plan.get("source_path_inventory_hash")
            or source_inventory_hash
            != binding.get("source_path_inventory_hash")
            or changed_pairs != plan.get("changed_source_pair_bindings")
            or changed_pairs != binding.get("changed_source_pair_bindings")
            or tuple(item["relative_path"] for item in source_bindings)
            != profile["source_paths"]
            or tuple(pair["relative_path"] for pair in changed_pairs)
            != profile["required_changed_paths"]
        ):
            raise EvidenceValidationError(
                "fixed-hold correction source paths differ from the exact protocol"
            )
        source_root = _SOURCE_ROOT.resolve()
        for source_binding in source_bindings:
            relative_path = _relative_source_path(
                "fixed-hold registered source path",
                source_binding.get("relative_path"),
            )
            new_artifact_hash = _digest(
                "fixed-hold registered source artifact",
                source_binding.get("new_artifact_hash"),
            )
            expected_bytes = opened.get(new_artifact_hash)
            current_path = (_SOURCE_ROOT / relative_path).resolve()
            try:
                if not current_path.is_relative_to(source_root):
                    raise EvidenceValidationError(
                        "fixed-hold registered source escapes the source root"
                    )
                current_bytes = current_path.read_bytes()
            except OSError as exc:
                raise EvidenceValidationError(
                    "fixed-hold registered source is unavailable"
                ) from exc
            if (
                type(expected_bytes) is not bytes
                or sha256(expected_bytes).hexdigest() != new_artifact_hash
                or current_bytes != expected_bytes
                or sha256(current_bytes).hexdigest() != new_artifact_hash
            ):
                raise EvidenceValidationError(
                    "fixed-hold registered source differs from the opened closure"
                )
        pair_results: list[dict[str, Any]] = []
        for pair in changed_pairs:
            relative_path = pair["relative_path"]
            expected_symbols = profile["allowed_changed_symbols"].get(
                relative_path
            )
            old_bytes = opened[pair["old_artifact_hash"]]
            new_bytes = opened[pair["new_artifact_hash"]]
            changed_symbols = changed_source_symbols(old_bytes, new_bytes)
            if (
                expected_symbols is None
                or frozenset(changed_symbols) != expected_symbols
            ):
                raise EvidenceValidationError(
                    "fixed-hold correction changed symbols exceed the registered boundary"
                )
            pair_results.append(
                {
                    "changed_symbols": list(changed_symbols),
                    "new_artifact_hash": pair["new_artifact_hash"],
                    "old_artifact_hash": pair["old_artifact_hash"],
                    "relative_path": relative_path,
                }
            )

        measurement_hashes = binding.get("measurement_artifact_hashes")
        if (
            not isinstance(measurement_hashes, list)
            or measurement_hashes != sorted(set(measurement_hashes))
            or any(identity not in opened for identity in measurement_hashes)
        ):
            raise EvidenceValidationError(
                "fixed-hold correction measurement set is invalid"
            )
        expected_by_path = {
            pair["relative_path"]: pair for pair in changed_pairs
        }
        measured_paths: set[str] = set()
        for identity in measurement_hashes:
            measurement = _canonical_document(
                opened[identity], label="fixed-hold correction measurement"
            )
            relative_path = measurement.get("relative_path")
            expected_pair = expected_by_path.get(relative_path)
            if (
                set(measurement) != _MEASUREMENT_FIELDS
                or measurement.get("schema")
                != SEMANTIC_EQUIVALENCE_MEASUREMENT_SCHEMA
                or measurement.get("validation_plan_hash")
                != request.validation_plan_hash
                or measurement.get("method")
                != FIXED_HOLD_AUTHORITY_CORRECTION_METHOD
                or expected_pair is None
                or relative_path in measured_paths
                or measurement.get("old_artifact_hash")
                != expected_pair["old_artifact_hash"]
                or measurement.get("new_artifact_hash")
                != expected_pair["new_artifact_hash"]
            ):
                raise EvidenceValidationError(
                    "fixed-hold correction measurement is incomplete or forged"
                )
            measured_paths.add(str(relative_path))
        if (
            measured_paths != set(expected_by_path)
            or len(measurement_hashes) != len(changed_pairs)
        ):
            raise EvidenceValidationError(
                "fixed-hold correction measurement coverage is incomplete"
            )

        conformance = _run_correction_conformance()
        surface_results = [
            {"surface_id": surface_id, "verdict": "passed"}
            for surface_id in claims
        ]
        expected_result = {
            "executable_id": plan["executable_id"],
            "job_hash": request.job_hash,
            "job_id": request.job_id,
            "measurement_artifact_hashes": measurement_hashes,
            "new_implementation_identity": new_identity,
            "old_implementation_identity": old_identity,
            "repair_id": plan["repair_id"],
            "schema": SEMANTIC_EQUIVALENCE_RESULT_SCHEMA,
            "surface_results": surface_results,
            "validation_plan_hash": request.validation_plan_hash,
            "verdict": "passed",
        }
        if set(result) != _RESULT_FIELDS or result != expected_result:
            raise EvidenceValidationError(
                "fixed-hold correction result was not independently reproduced"
            )
        facts = {
            "added_artifact_hashes": list(added_artifacts),
            "artifact_equivalence_method": (
                FIXED_HOLD_AUTHORITY_CORRECTION_METHOD
            ),
            "authority_deltas": {
                "candidate": 0,
                "holdout_reveal": 0,
                "scientific_claim": 0,
                "scientific_satisfaction": 0,
                "scientific_trial": 0,
            },
            "changed_source_pair_results": pair_results,
            "conformance_case_ids": list(conformance),
            "covered_surface_ids": list(claims),
            "new_implementation_artifact_hashes": list(new_artifacts),
            "new_implementation_identity": new_identity,
            "new_source_closure_hash": new_closure,
            "old_implementation_artifact_hashes": list(old_artifacts),
            "old_implementation_identity": old_identity,
            "old_source_closure_hash": old_closure,
            "pairing_status": "passed",
            "removed_artifact_hashes": list(removed_artifacts),
            "repair_id": plan["repair_id"],
            "result_manifest_hash": result_hash,
            "schema": FIXED_HOLD_AUTHORITY_CORRECTION_FACTS_SCHEMA,
            "surface_inventory_hash": plan["surface_inventory_hash"],
            "source_path_bindings": source_bindings,
            "source_path_inventory_hash": source_inventory_hash,
            "unchanged_artifact_hashes": list(unchanged_artifacts),
            "validation_plan_hash": request.validation_plan_hash,
            "validation_protocol": self.protocol,
            "validator_id": self.validator_id,
        }
        if set(facts) != _FIXED_HOLD_FACT_FIELDS:
            raise EvidenceValidationError(
                "fixed-hold correction validator produced an invalid facts shape"
            )
        return ValidatedEvidence(
            verdict="passed",
            claims=tuple(claims),
            measurement_artifact_hashes=tuple(measurement_hashes),
            facts=facts,
            scientific_eligible=False,
            candidate_eligible=False,
            release_eligible=False,
        )


__all__ = [
    "FIXED_HOLD_AUTHORITY_CORRECTION_NEW_IMPLEMENTATION_IDENTITY",
    "FIXED_HOLD_AUTHORITY_CORRECTION_OLD_IMPLEMENTATION_IDENTITY",
    "FIXED_HOLD_AUTHORITY_CORRECTION_VERIFICATION_SCHEMA",
    "FIXED_HOLD_AUTHORITY_CORRECTION_VALIDATOR_DEPENDENCIES",
    "FIXED_HOLD_AUTHORITY_CORRECTION_VALIDATOR_ID",
    "FIXED_HOLD_COST_AWARE_CROSS_STUDY_ORIGIN_NEW_IMPLEMENTATION_IDENTITY",
    "FIXED_HOLD_COST_AWARE_CROSS_STUDY_ORIGIN_OLD_IMPLEMENTATION_IDENTITY",
    "FIXED_HOLD_DIRECT_ORIGIN_CORRECTION_NEW_IMPLEMENTATION_IDENTITY",
    "FIXED_HOLD_DIRECT_ORIGIN_CORRECTION_OLD_IMPLEMENTATION_IDENTITY",
    "FIXED_HOLD_SCIENTIFIC_CHANGE_RETURN_NEW_IMPLEMENTATION_IDENTITY",
    "FIXED_HOLD_SCIENTIFIC_CHANGE_RETURN_OLD_IMPLEMENTATION_IDENTITY",
    "FixedHoldAuthorityCorrectionEquivalenceValidator",
    "changed_source_symbols",
    "fixed_hold_authority_correction_verification_manifest",
    "require_fixed_hold_authority_correction_verification",
]
