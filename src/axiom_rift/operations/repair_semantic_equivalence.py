"""Registered semantic-equivalence proof for in-place implementation Repair.

The generic path is deliberately narrow: for ``python.*`` implementations the
validator opens one exact source-closure manifest on each side, preserves its
relative-path roles, and compares changed ``.py`` bytes at the same path by
canonical AST.  The changing closure JSON is metadata, not Python source.
Caller-authored observations and path-free hash pairing are never equivalence
authority.  Behavior-changing code needs a protocol-specific validator or a
new scientific identity.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Mapping, Sequence
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.validation import (
    EvidenceValidationError,
    EvidenceValidationRequest,
    ValidatedEvidence,
    validator_identity,
    validator_implementation_sha256,
)


IMPLEMENTATION_REPAIR_V2_SCHEMA = "running_job_implementation_repair.v2"
SEMANTIC_EQUIVALENCE_PROTOCOL = "implementation_repair_semantic_equivalence.v1"
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
SEMANTIC_EQUIVALENCE_FACTS_SCHEMA = (
    "implementation_repair_semantic_equivalence_facts.v3"
)
PYTHON_AST_EQUIVALENCE_METHOD = "python_source_closure_path_ast.v1"
PYTHON_SOURCE_OBSERVATION_SCAN_METHOD = (
    "constant_only_python_provenance_scan.v1"
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
_BINDING_CATEGORIES = {
    "component_parity_binding": "component",
    "external_dependency_binding": "external",
    "holdout_binding": "scientific",
    "runtime_binding": "runtime",
    "scientific_binding": "scientific",
    "source_binding": "source",
}
_CLAIM_FIELDS = frozenset(
    {
        "dimensions",
        "evidence_depth",
        "evidence_modes",
        "planned_claims",
        "planned_materialization_cases",
        "planned_parity_surfaces",
        "transition_evidence",
    }
)
_DECISION_FIELDS = frozenset(
    {
        "architecture_chassis_identity",
        "portfolio_axis_identity",
        "portfolio_decision_id",
        "portfolio_snapshot_id",
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
_ARTIFACT_PAIR_FIELDS = {
    "equivalent",
    "new_artifact_hash",
    "new_ast_sha256",
    "old_artifact_hash",
    "old_ast_sha256",
    "relative_path",
}
_SOURCE_PATH_BINDING_FIELDS = {
    "changed",
    "new_artifact_hash",
    "old_artifact_hash",
    "relative_path",
}
_SOURCE_PAIR_BINDING_FIELDS = {
    "new_artifact_hash",
    "old_artifact_hash",
    "relative_path",
}
_FACT_FIELDS = {
    "added_artifact_hashes",
    "artifact_equivalence_method",
    "changed_source_pair_results",
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
    "source_observation_risks",
    "source_observation_scan_method",
    "unchanged_artifact_hashes",
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


class RepairSemanticEquivalenceError(ValueError):
    """One implementation Repair equivalence packet is malformed."""


def _ascii(label: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise RepairSemanticEquivalenceError(
            f"{label} must be non-empty ASCII"
        )
    return value


def _digest(label: str, value: object) -> str:
    text = _ascii(label, value)
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise RepairSemanticEquivalenceError(
            f"{label} must be a lowercase SHA-256 digest"
        )
    return text


def _typed_id(label: str, value: object, prefix: str) -> str:
    text = _ascii(label, value)
    if not text.startswith(prefix):
        raise RepairSemanticEquivalenceError(f"{label} is invalid")
    _digest(label, text.removeprefix(prefix))
    return text


def _digest_list(
    label: str,
    value: object,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if (
        not isinstance(value, (list, tuple))
        or (not allow_empty and not value)
        or any(type(item) is not str for item in value)
    ):
        raise RepairSemanticEquivalenceError(
            f"{label} must be a sorted unique digest list"
        )
    normalized = tuple(value)
    if normalized != tuple(sorted(set(normalized))):
        raise RepairSemanticEquivalenceError(
            f"{label} must be a sorted unique digest list"
        )
    return tuple(_digest(label, item) for item in normalized)


def _ascii_list(
    label: str,
    value: object,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if (
        not isinstance(value, (list, tuple))
        or (not allow_empty and not value)
        or any(type(item) is not str for item in value)
    ):
        raise RepairSemanticEquivalenceError(
            f"{label} must be a sorted unique ASCII list"
        )
    normalized = tuple(value)
    if normalized != tuple(sorted(set(normalized))):
        raise RepairSemanticEquivalenceError(
            f"{label} must be a sorted unique ASCII list"
        )
    return tuple(_ascii(label, item) for item in normalized)


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
    """Return exact old/new, unchanged, removed, and added partitions."""

    old_artifacts = _digest_list(
        "old implementation artifacts", old_artifact_hashes
    )
    new_artifacts = _digest_list(
        "new implementation artifacts", new_artifact_hashes
    )
    old_set = set(old_artifacts)
    new_set = set(new_artifacts)
    return (
        old_artifacts,
        new_artifacts,
        tuple(sorted(old_set & new_set)),
        tuple(sorted(old_set - new_set)),
        tuple(sorted(new_set - old_set)),
    )


def _relative_source_path(label: str, value: object) -> str:
    text = _ascii(label, value)
    candidate = PurePosixPath(text)
    if (
        candidate.is_absolute()
        or "\\" in text
        or candidate.as_posix() != text
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise RepairSemanticEquivalenceError(
            f"{label} must be one normalized relative POSIX path"
        )
    return text


def _source_closure(
    *,
    implementation_manifest: Mapping[str, Any],
    opened: Mapping[str, bytes],
    label: str,
) -> tuple[str, dict[str, str], tuple[str, ...]]:
    """Partition one implementation into exact source and non-source bytes."""

    artifacts = _digest_list(
        f"{label} implementation artifacts",
        implementation_manifest.get("artifact_hashes"),
    )
    candidates: list[tuple[str, dict[str, Any]]] = []
    for identity in artifacts:
        content = opened.get(identity)
        if type(content) is not bytes or sha256(content).hexdigest() != identity:
            raise RepairSemanticEquivalenceError(
                f"{label} implementation artifact bytes are invalid"
            )
        try:
            value = parse_canonical(content)
        except (TypeError, ValueError):
            continue
        if (
            isinstance(value, dict)
            and value.get("schema") == _SOURCE_CLOSURE_SCHEMA
        ):
            candidates.append((identity, value))
    if len(candidates) != 1:
        raise RepairSemanticEquivalenceError(
            f"{label} implementation requires one unambiguous source closure"
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
        raise RepairSemanticEquivalenceError(
            f"{label} source closure authority is invalid"
        )
    path_hashes: dict[str, str] = {}
    ordered_paths: list[str] = []
    for dependency in dependencies:
        if (
            not isinstance(dependency, Mapping)
            or set(dependency) != _SOURCE_CLOSURE_ENTRY_FIELDS
        ):
            raise RepairSemanticEquivalenceError(
                f"{label} source closure dependency is invalid"
            )
        relative_path = _relative_source_path(
            f"{label} source closure path", dependency.get("path")
        )
        identity = _digest(
            f"{label} source closure artifact", dependency.get("sha256")
        )
        if relative_path in path_hashes or identity not in opened:
            raise RepairSemanticEquivalenceError(
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
        raise RepairSemanticEquivalenceError(
            f"{label} source closure does not explain its declared source artifacts"
        )
    non_source_artifacts = tuple(sorted(set(artifacts) - source_artifacts))
    return closure_hash, path_hashes, non_source_artifacts


def _source_path_comparison(
    *,
    old_paths: Mapping[str, str],
    new_paths: Mapping[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, str]], str]:
    """Bind identical path roles and derive the exact changed path pairs."""

    if set(old_paths) != set(new_paths) or not old_paths:
        raise RepairSemanticEquivalenceError(
            "old/new source closures must preserve one exact path inventory"
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


def _python_ast_sha256(content: bytes) -> str | None:
    """Hash Python syntax while excluding locations, comments, and layout."""

    try:
        tree = ast.parse(content, mode="exec", type_comments=True)
    except (SyntaxError, TypeError, ValueError):
        return None
    canonical_ast = ast.dump(
        tree,
        annotate_fields=True,
        include_attributes=False,
    )
    return sha256(canonical_ast.encode("utf-8")).hexdigest()


def _constant_literal(node: ast.AST | None) -> bool:
    if node is None:
        return True
    if isinstance(node, ast.Constant):
        return isinstance(
            node.value,
            (bytes, complex, float, int, str, type(None)),
        )
    if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        return all(_constant_literal(item) for item in node.elts)
    if isinstance(node, ast.Dict):
        return all(_constant_literal(item) for item in node.keys) and all(
            _constant_literal(item) for item in node.values
        )
    if isinstance(node, ast.UnaryOp) and isinstance(
        node.op, (ast.UAdd, ast.USub)
    ):
        return _constant_literal(node.operand)
    return False


def _constant_only_function(node: ast.FunctionDef) -> bool:
    arguments = (
        *node.args.posonlyargs,
        *node.args.args,
        *node.args.kwonlyargs,
        *((node.args.vararg,) if node.args.vararg is not None else ()),
        *((node.args.kwarg,) if node.args.kwarg is not None else ()),
    )
    if (
        node.decorator_list
        or node.returns is not None
        or node.type_comment is not None
        or any(argument.annotation is not None for argument in arguments)
        or any(not _constant_literal(value) for value in node.args.defaults)
        or any(
            value is not None and not _constant_literal(value)
            for value in node.args.kw_defaults
        )
    ):
        return False
    body = list(node.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return (
        not body
        or (
            len(body) == 1
            and (
                isinstance(body[0], ast.Pass)
                or (
                    isinstance(body[0], ast.Return)
                    and _constant_literal(body[0].value)
                )
            )
        )
    )


def _constant_only_python_provenance_reason(content: bytes) -> str | None:
    """Prove a tiny source-independent Python subset or explain rejection."""

    try:
        tree = ast.parse(content, mode="exec", type_comments=True)
    except (SyntaxError, TypeError, ValueError):
        return "unparseable_python"
    for statement in tree.body:
        if (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            continue
        if isinstance(statement, ast.FunctionDef) and _constant_only_function(
            statement
        ):
            continue
        return f"unsafe_{type(statement).__name__}"
    return None


def _source_observation_risks(
    *,
    old_paths: Mapping[str, str],
    new_paths: Mapping[str, str],
    opened: Mapping[str, bytes],
) -> tuple[str, ...]:
    risks: set[str] = set()
    for side, path_hashes in (("old", old_paths), ("new", new_paths)):
        for relative_path, identity in sorted(path_hashes.items()):
            if PurePosixPath(relative_path).suffix != ".py":
                continue
            reason = _constant_only_python_provenance_reason(opened[identity])
            if reason is not None:
                risks.add(f"{side}:{relative_path}:{reason}")
    return tuple(sorted(risks))


def require_passed_semantic_equivalence_facts(
    *,
    binding: Mapping[str, Any],
    facts: Mapping[str, Any],
) -> None:
    """Require a passed trace to bind exact path-role AST equivalence."""

    if (
        not isinstance(binding, Mapping)
        or set(binding) != _BINDING_FIELDS
        or binding.get("schema") != SEMANTIC_EQUIVALENCE_BINDING_SCHEMA
        or binding.get("validator_id") != SEMANTIC_EQUIVALENCE_VALIDATOR_ID
    ):
        raise RepairSemanticEquivalenceError(
            "semantic-equivalence binding authority is invalid"
        )
    claims = _ascii_list(
        "semantic-equivalence binding claims", binding.get("claims")
    )
    old_identity = _digest(
        "old implementation identity",
        binding.get("old_implementation_identity"),
    )
    new_identity = _digest(
        "new implementation identity",
        binding.get("new_implementation_identity"),
    )
    if old_identity == new_identity:
        raise RepairSemanticEquivalenceError(
            "semantic-equivalence implementation identity did not change"
        )
    (
        old_artifacts,
        new_artifacts,
        unchanged_artifacts,
        removed_artifacts,
        added_artifacts,
    ) = _artifact_partition(
        old_artifact_hashes=binding.get(
            "old_implementation_artifact_hashes"
        ),
        new_artifact_hashes=binding.get(
            "new_implementation_artifact_hashes"
        ),
    )
    old_closure = _digest(
        "old source closure", binding.get("old_source_closure_hash")
    )
    new_closure = _digest(
        "new source closure", binding.get("new_source_closure_hash")
    )
    source_inventory_hash = _digest(
        "source path inventory", binding.get("source_path_inventory_hash")
    )
    if (
        old_closure == new_closure
        or old_closure not in removed_artifacts
        or new_closure not in added_artifacts
    ):
        raise RepairSemanticEquivalenceError(
            "passed semantic equivalence lacks changed source-closure authority"
        )
    repair_id = _typed_id("Repair id", binding.get("repair_id"), "repair:")
    result_hash = _digest(
        "semantic-equivalence result", binding.get("result_manifest_hash")
    )
    inventory_hash = _digest(
        "semantic-equivalence surface inventory",
        binding.get("surface_inventory_hash"),
    )
    plan_hash = _digest(
        "semantic-equivalence validation plan",
        binding.get("validation_plan_hash"),
    )
    measurements = _digest_list(
        "semantic-equivalence measurements",
        binding.get("measurement_artifact_hashes"),
    )
    declared = _digest_list(
        "semantic-equivalence declared artifacts",
        binding.get("declared_artifact_hashes"),
    )
    if set(declared) != {
        plan_hash,
        result_hash,
        old_identity,
        new_identity,
        *old_artifacts,
        *new_artifacts,
        *measurements,
    }:
        raise RepairSemanticEquivalenceError(
            "semantic-equivalence declared artifact closure is not exact"
        )
    expected_changed = binding.get("changed_source_pair_bindings")
    if not isinstance(expected_changed, list) or not expected_changed:
        raise RepairSemanticEquivalenceError(
            "semantic-equivalence changed source pairs are absent"
        )
    normalized_expected: list[dict[str, str]] = []
    seen_changed_paths: set[str] = set()
    for pair in expected_changed:
        if (
            not isinstance(pair, Mapping)
            or set(pair) != _SOURCE_PAIR_BINDING_FIELDS
        ):
            raise RepairSemanticEquivalenceError(
                "semantic-equivalence changed source pair is invalid"
            )
        relative_path = _relative_source_path(
            "changed source path", pair.get("relative_path")
        )
        old_artifact = _digest(
            "changed old source artifact", pair.get("old_artifact_hash")
        )
        new_artifact = _digest(
            "changed new source artifact", pair.get("new_artifact_hash")
        )
        if (
            relative_path in seen_changed_paths
            or old_artifact == new_artifact
            or PurePosixPath(relative_path).suffix != ".py"
        ):
            raise RepairSemanticEquivalenceError(
                "semantic-equivalence changed source paths are ambiguous"
            )
        seen_changed_paths.add(relative_path)
        normalized_expected.append(
            {
                "new_artifact_hash": new_artifact,
                "old_artifact_hash": old_artifact,
                "relative_path": relative_path,
            }
        )
    if normalized_expected != sorted(
        normalized_expected, key=lambda item: item["relative_path"]
    ) or len(measurements) != len(normalized_expected):
        raise RepairSemanticEquivalenceError(
            "semantic-equivalence changed source pair coverage is incomplete"
        )
    if not isinstance(facts, Mapping) or set(facts) != _FACT_FIELDS:
        raise RepairSemanticEquivalenceError(
            "semantic-equivalence facts schema is invalid"
        )
    if (
        facts.get("schema") != SEMANTIC_EQUIVALENCE_FACTS_SCHEMA
        or facts.get("artifact_equivalence_method")
        != PYTHON_AST_EQUIVALENCE_METHOD
        or facts.get("source_observation_scan_method")
        != PYTHON_SOURCE_OBSERVATION_SCAN_METHOD
        or facts.get("source_observation_risks") != []
        or facts.get("pairing_status") != "passed"
        or facts.get("covered_surface_ids") != list(claims)
        or facts.get("old_implementation_identity") != old_identity
        or facts.get("new_implementation_identity") != new_identity
        or facts.get("old_source_closure_hash") != old_closure
        or facts.get("new_source_closure_hash") != new_closure
        or facts.get("old_implementation_artifact_hashes")
        != list(old_artifacts)
        or facts.get("new_implementation_artifact_hashes")
        != list(new_artifacts)
        or facts.get("unchanged_artifact_hashes")
        != list(unchanged_artifacts)
        or facts.get("removed_artifact_hashes") != list(removed_artifacts)
        or facts.get("added_artifact_hashes") != list(added_artifacts)
        or facts.get("repair_id") != repair_id
        or facts.get("result_manifest_hash") != result_hash
        or facts.get("surface_inventory_hash") != inventory_hash
        or facts.get("source_path_inventory_hash") != source_inventory_hash
        or facts.get("validation_plan_hash") != plan_hash
    ):
        raise RepairSemanticEquivalenceError(
            "semantic-equivalence facts differ from their exact binding"
        )
    path_bindings = facts.get("source_path_bindings")
    if not isinstance(path_bindings, list) or not path_bindings:
        raise RepairSemanticEquivalenceError(
            "semantic-equivalence source path bindings are absent"
        )
    normalized_bindings: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for path_binding in path_bindings:
        if (
            not isinstance(path_binding, Mapping)
            or set(path_binding) != _SOURCE_PATH_BINDING_FIELDS
        ):
            raise RepairSemanticEquivalenceError(
                "semantic-equivalence source path binding is invalid"
            )
        relative_path = _relative_source_path(
            "source path binding", path_binding.get("relative_path")
        )
        old_artifact = _digest(
            "source path old artifact",
            path_binding.get("old_artifact_hash"),
        )
        new_artifact = _digest(
            "source path new artifact",
            path_binding.get("new_artifact_hash"),
        )
        changed = path_binding.get("changed")
        if (
            type(changed) is not bool
            or changed != (old_artifact != new_artifact)
            or relative_path in seen_paths
        ):
            raise RepairSemanticEquivalenceError(
                "semantic-equivalence source path role is ambiguous"
            )
        seen_paths.add(relative_path)
        normalized_bindings.append(
            {
                "changed": changed,
                "new_artifact_hash": new_artifact,
                "old_artifact_hash": old_artifact,
                "relative_path": relative_path,
            }
        )
    if normalized_bindings != sorted(
        normalized_bindings, key=lambda item: item["relative_path"]
    ):
        raise RepairSemanticEquivalenceError(
            "semantic-equivalence source path bindings are not canonical"
        )
    derived_changed = [
        {
            "new_artifact_hash": item["new_artifact_hash"],
            "old_artifact_hash": item["old_artifact_hash"],
            "relative_path": item["relative_path"],
        }
        for item in normalized_bindings
        if item["changed"]
    ]
    if (
        derived_changed != normalized_expected
        or canonical_digest(
            domain="implementation-repair-source-path-inventory",
            payload={"relative_paths": sorted(seen_paths)},
        )
        != source_inventory_hash
        or set(old_artifacts)
        != {
            old_closure,
            *(item["old_artifact_hash"] for item in normalized_bindings),
        }
        or set(new_artifacts)
        != {
            new_closure,
            *(item["new_artifact_hash"] for item in normalized_bindings),
        }
    ):
        raise RepairSemanticEquivalenceError(
            "semantic-equivalence source closure differs from its path bindings"
        )
    pairs = facts.get("changed_source_pair_results")
    if not isinstance(pairs, list) or len(pairs) != len(normalized_expected):
        raise RepairSemanticEquivalenceError(
            "semantic-equivalence changed source result coverage is incomplete"
        )
    normalized_results: list[dict[str, Any]] = []
    for pair in pairs:
        if not isinstance(pair, Mapping) or set(pair) != _ARTIFACT_PAIR_FIELDS:
            raise RepairSemanticEquivalenceError(
                "semantic-equivalence changed source result is invalid"
            )
        relative_path = _relative_source_path(
            "paired source path", pair.get("relative_path")
        )
        old_artifact = _digest(
            "paired old source artifact",
            pair.get("old_artifact_hash"),
        )
        new_artifact = _digest(
            "paired new source artifact",
            pair.get("new_artifact_hash"),
        )
        old_ast = _digest("old source AST", pair.get("old_ast_sha256"))
        new_ast = _digest("new source AST", pair.get("new_ast_sha256"))
        if pair.get("equivalent") is not True or old_ast != new_ast:
            raise RepairSemanticEquivalenceError(
                "passed source path pair is not AST-equivalent"
            )
        normalized_results.append(
            {
                "equivalent": True,
                "new_artifact_hash": new_artifact,
                "new_ast_sha256": new_ast,
                "old_artifact_hash": old_artifact,
                "old_ast_sha256": old_ast,
                "relative_path": relative_path,
            }
        )
    result_bindings = [
        {
            "new_artifact_hash": item["new_artifact_hash"],
            "old_artifact_hash": item["old_artifact_hash"],
            "relative_path": item["relative_path"],
        }
        for item in normalized_results
    ]
    if result_bindings != normalized_expected:
        raise RepairSemanticEquivalenceError(
            "semantic-equivalence changed source results differ from exact paths"
        )


def _plain(value: object) -> Any:
    """Return a canonical mutable copy of a frozen validation value."""

    def thaw(item: object) -> Any:
        if isinstance(item, Mapping):
            return {str(key): thaw(child) for key, child in item.items()}
        if isinstance(item, (list, tuple)):
            return [thaw(child) for child in item]
        return item

    return parse_canonical(canonical_bytes(thaw(value)))


def _implementation_manifest(
    value: object,
    *,
    identity: str,
    label: str,
) -> dict[str, Any]:
    _digest(f"{label} identity", identity)
    if (
        not isinstance(value, Mapping)
        or set(value) != _IMPLEMENTATION_MANIFEST_FIELDS
        or value.get("schema") != "job_implementation_evidence.v1"
    ):
        raise RepairSemanticEquivalenceError(
            f"{label} implementation manifest is invalid"
        )
    manifest = _plain(value)
    if (
        not isinstance(manifest, dict)
        or sha256(canonical_bytes(manifest)).hexdigest() != identity
    ):
        raise RepairSemanticEquivalenceError(
            f"{label} implementation identity differs from its manifest"
        )
    _ascii(f"{label} callable", manifest.get("callable_identity"))
    _ascii(f"{label} protocol", manifest.get("protocol"))
    _digest_list(f"{label} implementation artifacts", manifest.get("artifact_hashes"))
    return manifest


def _surface(*, category: str, path: str, value: object) -> dict[str, str]:
    if category not in _SURFACE_CATEGORIES:
        raise RepairSemanticEquivalenceError(
            "implementation Repair surface category is invalid"
        )
    _ascii("implementation Repair surface path", path)
    value_hash = canonical_digest(
        domain="implementation-repair-semantic-surface-value",
        payload={"value": _plain(value)},
    )
    payload = {
        "category": category,
        "path": path,
        "value_hash": value_hash,
    }
    return {
        **payload,
        "surface_id": "repair-surface:"
        + canonical_digest(
            domain="implementation-repair-semantic-surface",
            payload=payload,
        ),
    }


def _binding_leaf_category(
    *,
    default: str,
    path: tuple[str, ...],
) -> str:
    if any(part in _CLAIM_FIELDS for part in path):
        return "claim"
    if any(part in _DECISION_FIELDS for part in path):
        return "decision"
    if "numeric_tolerances" in path:
        return "cost"
    return default


def _leaf_surfaces(
    *,
    category: str,
    path: str,
    value: object,
    key_path: tuple[str, ...] = (),
) -> list[dict[str, str]]:
    surfaces: list[dict[str, str]] = []
    if isinstance(value, Mapping):
        if not value:
            surfaces.append(_surface(category=category, path=path, value={}))
        for key in sorted(value):
            text = _ascii("semantic binding key", key)
            surfaces.extend(
                _leaf_surfaces(
                    category=_binding_leaf_category(
                        default=category,
                        path=(*key_path, text),
                    ),
                    path=f"{path}.{text}",
                    value=value[key],
                    key_path=(*key_path, text),
                )
            )
        return surfaces
    if isinstance(value, (list, tuple)):
        if not value:
            surfaces.append(_surface(category=category, path=path, value=[]))
        for ordinal, item in enumerate(value):
            surfaces.extend(
                _leaf_surfaces(
                    category=category,
                    path=f"{path}[{ordinal}]",
                    value=item,
                    key_path=key_path,
                )
            )
        return surfaces
    surfaces.append(_surface(category=category, path=path, value=value))
    return surfaces


def derive_semantic_surface_inventory(
    *,
    job_spec: Mapping[str, Any],
    executable_manifest: Mapping[str, Any],
    implementation_protocol: str,
) -> tuple[dict[str, str], ...]:
    """Derive every frozen semantic surface that an in-place Repair preserves."""

    if (
        not isinstance(job_spec, Mapping)
        or not isinstance(executable_manifest, Mapping)
        or executable_manifest.get("schema") != "executable_spec.v1"
    ):
        raise RepairSemanticEquivalenceError(
            "Executable-bound Repair context is invalid"
        )
    callable_identity = _ascii(
        "Job callable identity", job_spec.get("callable_identity")
    )
    protocol = _ascii("implementation protocol", implementation_protocol)
    surfaces: list[dict[str, str]] = [
        _surface(
            category="callable",
            path="job.callable_identity",
            value=callable_identity,
        ),
        _surface(
            category="protocol",
            path="implementation.protocol",
            value=protocol,
        ),
        _surface(
            category="claim",
            path="job.evidence_subject",
            value=job_spec.get("evidence_subject"),
        ),
        _surface(
            category="lifecycle",
            path="job.resume_action",
            value=job_spec.get("resume_action"),
        ),
        _surface(
            category="claim",
            path="job.output_contract",
            value={
                "expected_outputs": job_spec.get("expected_outputs"),
                "output_classes": job_spec.get("output_classes"),
            },
        ),
        _surface(
            category="source",
            path="job.input_hashes",
            value=job_spec.get("input_hashes"),
        ),
        _surface(
            category="component",
            path="executable.exact_manifest",
            value=executable_manifest,
        ),
        _surface(
            category="decision",
            path="executable.decision_contract",
            value={
                "engine_contract": executable_manifest.get("engine_contract"),
                "parameters": executable_manifest.get("parameters"),
            },
        ),
        _surface(
            category="lifecycle",
            path="executable.clock_contract",
            value=executable_manifest.get("clock_contract"),
        ),
        _surface(
            category="cost",
            path="executable.cost_contract",
            value=executable_manifest.get("cost_contract"),
        ),
        _surface(
            category="source",
            path="executable.source_contract",
            value={
                "data_contract": executable_manifest.get("data_contract"),
                "source_contracts": executable_manifest.get("source_contracts"),
                "split_contract": executable_manifest.get("split_contract"),
            },
        ),
    ]
    for name, category in sorted(_BINDING_CATEGORIES.items()):
        binding = job_spec.get(name)
        if binding is None:
            continue
        surfaces.append(
            _surface(
                category=category,
                path=f"job.{name}.exact_binding",
                value=binding,
            )
        )
        surfaces.extend(
            _leaf_surfaces(
                category=category,
                path=f"job.{name}",
                value=binding,
            )
        )

    manifests = executable_manifest.get("component_manifests")
    if not isinstance(manifests, list) or not manifests:
        raise RepairSemanticEquivalenceError(
            "Executable component semantic surfaces are unavailable"
        )
    for ordinal, manifest in enumerate(manifests):
        if not isinstance(manifest, Mapping):
            raise RepairSemanticEquivalenceError(
                "Executable component semantic surface is invalid"
            )
        protocol_value = _ascii(
            "Executable component protocol", manifest.get("protocol")
        )
        domain = protocol_value.split(".", 1)[0]
        surfaces.append(
            _surface(
                category="component",
                path=f"executable.component_manifests[{ordinal}]",
                value=manifest,
            )
        )
        specialized = (
            "lifecycle"
            if domain == "lifecycle"
            else (
                "cost"
                if domain in {"execution", "risk", "trade"}
                else (
                    "decision"
                    if domain
                    in {
                        "calibration",
                        "feature",
                        "label",
                        "model",
                        "selector",
                    }
                    else None
                )
            )
        )
        if specialized is not None:
            surfaces.append(
                _surface(
                    category=specialized,
                    path=(
                        f"executable.{specialized}_component_surfaces[{ordinal}]"
                    ),
                    value=manifest,
                )
            )
    ordered = tuple(
        sorted(
            surfaces,
            key=lambda item: (item["category"], item["path"], item["surface_id"]),
        )
    )
    ids = tuple(item["surface_id"] for item in ordered)
    paths = tuple(item["path"] for item in ordered)
    if len(set(ids)) != len(ids) or len(set(paths)) != len(paths):
        raise RepairSemanticEquivalenceError(
            "Writer-derived semantic surface inventory is ambiguous"
        )
    return ordered


def build_semantic_equivalence_plan(
    *,
    validator_id: str,
    repair_id: str,
    job_id: str,
    job_hash: str,
    executable_id: str,
    job_spec: Mapping[str, Any],
    executable_manifest: Mapping[str, Any],
    old_implementation_identity: str,
    old_implementation_manifest: Mapping[str, Any],
    new_implementation_identity: str,
    new_implementation_manifest: Mapping[str, Any],
    artifact_reader: Callable[[str], bytes],
) -> dict[str, Any]:
    """Build the exact plan that the Writer recomputes before validation."""

    validator = _ascii("semantic-equivalence validator", validator_id)
    _digest(
        "semantic-equivalence validator identity",
        validator.removeprefix("validator:"),
    )
    repair = _typed_id("Repair id", repair_id, "repair:")
    job = _typed_id("Job id", job_id, "job:")
    _digest("Job hash", job_hash)
    executable = _typed_id("Executable id", executable_id, "executable:")
    old_manifest = _implementation_manifest(
        old_implementation_manifest,
        identity=old_implementation_identity,
        label="old",
    )
    new_manifest = _implementation_manifest(
        new_implementation_manifest,
        identity=new_implementation_identity,
        label="new",
    )
    if old_implementation_identity == new_implementation_identity:
        raise RepairSemanticEquivalenceError(
            "implementation Repair must change implementation identity"
        )
    if (
        old_manifest["callable_identity"] != job_spec.get("callable_identity")
        or new_manifest["callable_identity"] != job_spec.get("callable_identity")
        or old_manifest["protocol"] != new_manifest["protocol"]
    ):
        raise RepairSemanticEquivalenceError(
            "implementation Repair changes callable or protocol semantics"
        )
    if not callable(artifact_reader):
        raise RepairSemanticEquivalenceError(
            "implementation Repair source artifact reader is unavailable"
        )
    opened: dict[str, bytes] = {}
    try:
        for identity in sorted(
            {
                *old_manifest["artifact_hashes"],
                *new_manifest["artifact_hashes"],
            }
        ):
            content = artifact_reader(identity)
            if type(content) is not bytes:
                raise RepairSemanticEquivalenceError(
                    "implementation Repair source artifact reader returned non-bytes"
                )
            opened[identity] = content
    except RepairSemanticEquivalenceError:
        raise
    except Exception as exc:
        raise RepairSemanticEquivalenceError(
            "implementation Repair source closure bytes are unavailable"
        ) from exc
    old_closure, old_paths, old_non_source_artifacts = _source_closure(
        implementation_manifest=old_manifest,
        opened=opened,
        label="old",
    )
    new_closure, new_paths, new_non_source_artifacts = _source_closure(
        implementation_manifest=new_manifest,
        opened=opened,
        label="new",
    )
    if old_non_source_artifacts != new_non_source_artifacts:
        raise RepairSemanticEquivalenceError(
            "implementation Repair changes the exact non-source artifact closure"
        )
    _source_bindings, changed_source_pairs, source_inventory_hash = (
        _source_path_comparison(old_paths=old_paths, new_paths=new_paths)
    )
    if not changed_source_pairs:
        raise RepairSemanticEquivalenceError(
            "implementation Repair source closure has no changed path"
        )
    inventory = derive_semantic_surface_inventory(
        job_spec=job_spec,
        executable_manifest=executable_manifest,
        implementation_protocol=old_manifest["protocol"],
    )
    inventory_list = [dict(item) for item in inventory]
    inventory_hash = canonical_digest(
        domain="implementation-repair-semantic-surface-inventory",
        payload={"surface_inventory": inventory_list},
    )
    claims = sorted(item["surface_id"] for item in inventory)
    return {
        "changed_source_pair_bindings": changed_source_pairs,
        "claims": claims,
        "executable_id": executable,
        "job_hash": job_hash,
        "job_id": job,
        "new_implementation_artifact_hashes": list(
            new_manifest["artifact_hashes"]
        ),
        "new_implementation_identity": new_implementation_identity,
        "new_source_closure_hash": new_closure,
        "old_implementation_artifact_hashes": list(
            old_manifest["artifact_hashes"]
        ),
        "old_implementation_identity": old_implementation_identity,
        "old_source_closure_hash": old_closure,
        "protocol": SEMANTIC_EQUIVALENCE_PROTOCOL,
        "repair_id": repair,
        "schema": SEMANTIC_EQUIVALENCE_PLAN_SCHEMA,
        "surface_inventory": inventory_list,
        "surface_inventory_hash": inventory_hash,
        "source_path_inventory_hash": source_inventory_hash,
        "validator_id": validator,
    }


def semantic_equivalence_measurement(
    *,
    validation_plan_hash: str,
    relative_path: str,
    old_artifact_hash: str,
    new_artifact_hash: str,
) -> dict[str, Any]:
    """Declare one changed-artifact pair; the validator opens and compares it."""

    _digest("semantic-equivalence validation plan", validation_plan_hash)
    path = _relative_source_path(
        "semantic-equivalence source path", relative_path
    )
    old_identity = _digest(
        "old semantic-equivalence artifact", old_artifact_hash
    )
    new_identity = _digest(
        "new semantic-equivalence artifact", new_artifact_hash
    )
    if old_identity == new_identity:
        raise RepairSemanticEquivalenceError(
            "semantic-equivalence measurement cannot pair one unchanged artifact"
        )
    return {
        "method": PYTHON_AST_EQUIVALENCE_METHOD,
        "new_artifact_hash": new_identity,
        "old_artifact_hash": old_identity,
        "relative_path": path,
        "schema": SEMANTIC_EQUIVALENCE_MEASUREMENT_SCHEMA,
        "validation_plan_hash": validation_plan_hash,
    }


def semantic_equivalence_result_manifest(
    *,
    plan: Mapping[str, Any],
    validation_plan_hash: str,
    measurement_artifact_hashes: Sequence[str],
    surface_verdicts: Mapping[str, str],
) -> dict[str, Any]:
    """Render the result packet that the validator independently recomputes."""

    _digest("semantic-equivalence validation plan", validation_plan_hash)
    measurements = _digest_list(
        "semantic-equivalence measurements",
        tuple(measurement_artifact_hashes),
        allow_empty=True,
    )
    claims = _ascii_list(
        "semantic-equivalence plan claims",
        plan.get("claims"),
    )
    if set(surface_verdicts) != set(claims) or any(
        value not in {"failed", "not_evaluable", "passed"}
        for value in surface_verdicts.values()
    ):
        raise RepairSemanticEquivalenceError(
            "semantic-equivalence surface verdict set is incomplete"
        )
    ordered = [
        {"surface_id": surface_id, "verdict": surface_verdicts[surface_id]}
        for surface_id in claims
    ]
    verdict = (
        "failed"
        if any(item["verdict"] == "failed" for item in ordered)
        else (
            "not_evaluable"
            if any(item["verdict"] == "not_evaluable" for item in ordered)
            else "passed"
        )
    )
    return {
        "executable_id": plan.get("executable_id"),
        "job_hash": plan.get("job_hash"),
        "job_id": plan.get("job_id"),
        "measurement_artifact_hashes": list(measurements),
        "new_implementation_identity": plan.get(
            "new_implementation_identity"
        ),
        "old_implementation_identity": plan.get(
            "old_implementation_identity"
        ),
        "repair_id": plan.get("repair_id"),
        "schema": SEMANTIC_EQUIVALENCE_RESULT_SCHEMA,
        "surface_results": ordered,
        "validation_plan_hash": validation_plan_hash,
        "verdict": verdict,
    }


def build_semantic_equivalence_binding(
    *,
    plan: Mapping[str, Any],
    validation_plan_hash: str,
    result_manifest_hash: str,
    measurement_artifact_hashes: Sequence[str],
) -> dict[str, Any]:
    """Build the immutable registry request binding from one exact plan."""

    if not isinstance(plan, Mapping) or set(plan) != _PLAN_FIELDS:
        raise RepairSemanticEquivalenceError(
            "semantic-equivalence validation plan schema is invalid"
        )
    _digest("semantic-equivalence validation plan", validation_plan_hash)
    _digest("semantic-equivalence result", result_manifest_hash)
    measurements = _digest_list(
        "semantic-equivalence measurements",
        tuple(measurement_artifact_hashes),
        allow_empty=True,
    )
    old_artifacts = _digest_list(
        "old implementation artifacts",
        plan.get("old_implementation_artifact_hashes"),
    )
    new_artifacts = _digest_list(
        "new implementation artifacts",
        plan.get("new_implementation_artifact_hashes"),
    )
    claims = _ascii_list("semantic-equivalence claims", plan.get("claims"))
    declared = sorted(
        {
            validation_plan_hash,
            result_manifest_hash,
            plan["old_implementation_identity"],
            plan["new_implementation_identity"],
            *old_artifacts,
            *new_artifacts,
            *measurements,
        }
    )
    return {
        "changed_source_pair_bindings": plan[
            "changed_source_pair_bindings"
        ],
        "claims": list(claims),
        "declared_artifact_hashes": declared,
        "executable_id": plan["executable_id"],
        "measurement_artifact_hashes": list(measurements),
        "new_implementation_artifact_hashes": list(new_artifacts),
        "new_implementation_identity": plan["new_implementation_identity"],
        "new_source_closure_hash": plan["new_source_closure_hash"],
        "old_implementation_artifact_hashes": list(old_artifacts),
        "old_implementation_identity": plan["old_implementation_identity"],
        "old_source_closure_hash": plan["old_source_closure_hash"],
        "repair_id": plan["repair_id"],
        "result_manifest_hash": result_manifest_hash,
        "schema": SEMANTIC_EQUIVALENCE_BINDING_SCHEMA,
        "surface_inventory_hash": plan["surface_inventory_hash"],
        "source_path_inventory_hash": plan["source_path_inventory_hash"],
        "validation_plan_hash": validation_plan_hash,
        "validator_id": plan["validator_id"],
    }


def _canonical_document(content: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = parse_canonical(content)
    except (TypeError, ValueError) as exc:
        raise EvidenceValidationError(f"{label} is not canonical") from exc
    if not isinstance(value, dict):
        raise EvidenceValidationError(f"{label} must be an object")
    return value


_THIS_IMPLEMENTATION = Path(__file__).resolve()
_AXIOM_PACKAGE_ROOT = _THIS_IMPLEMENTATION.parents[1]
SEMANTIC_EQUIVALENCE_VALIDATOR_DEPENDENCIES = tuple(
    sorted(
        {
            _AXIOM_PACKAGE_ROOT / "core" / "canonical.py",
            _AXIOM_PACKAGE_ROOT / "core" / "identity.py",
        },
        key=lambda path: path.as_posix(),
    )
)
SEMANTIC_EQUIVALENCE_VALIDATOR_ID = validator_identity(
    protocol=SEMANTIC_EQUIVALENCE_PROTOCOL,
    domains=frozenset({"scientific"}),
    implementation_sha256=validator_implementation_sha256(
        implementation_path=_THIS_IMPLEMENTATION,
        dependency_paths=SEMANTIC_EQUIVALENCE_VALIDATOR_DEPENDENCIES,
    ),
)


class ImplementationRepairSemanticEquivalenceValidator:
    """Recompute complete in-place implementation equivalence from artifacts."""

    validator_id = SEMANTIC_EQUIVALENCE_VALIDATOR_ID
    domains = frozenset({"scientific"})
    implementation_path = _THIS_IMPLEMENTATION
    dependency_paths = SEMANTIC_EQUIVALENCE_VALIDATOR_DEPENDENCIES
    protocol = SEMANTIC_EQUIVALENCE_PROTOCOL

    def validate(self, request: EvidenceValidationRequest) -> ValidatedEvidence:
        if (
            request.domain != "scientific"
            or request.engineering_fixture
            or request.validator_id != self.validator_id
        ):
            raise EvidenceValidationError(
                "implementation Repair semantic-equivalence request is unauthorized"
            )
        binding = _plain(request.binding)
        if (
            not isinstance(binding, dict)
            or set(binding) != _BINDING_FIELDS
            or binding.get("schema") != SEMANTIC_EQUIVALENCE_BINDING_SCHEMA
            or binding.get("validator_id") != self.validator_id
            or binding.get("validation_plan_hash")
            != request.validation_plan_hash
        ):
            raise EvidenceValidationError(
                "implementation Repair semantic-equivalence binding is invalid"
            )
        artifacts = {artifact.sha256: artifact for artifact in request.artifacts}
        if len(artifacts) != len(request.artifacts):
            raise EvidenceValidationError(
                "implementation Repair validator artifacts are ambiguous"
            )
        declared_hashes = binding.get("declared_artifact_hashes")
        if (
            not isinstance(declared_hashes, list)
            or declared_hashes != sorted(set(declared_hashes))
            or set(declared_hashes) != set(artifacts)
        ):
            raise EvidenceValidationError(
                "implementation Repair validator artifact set is not exact"
            )
        opened = {
            identity: artifact.read_bytes()
            for identity, artifact in artifacts.items()
        }
        plan = _canonical_document(
            opened[request.validation_plan_hash],
            label="implementation Repair validation plan",
        )
        result_hash = binding.get("result_manifest_hash")
        if type(result_hash) is not str or result_hash not in opened:
            raise EvidenceValidationError(
                "implementation Repair result artifact is absent"
            )
        result = _canonical_document(
            opened[result_hash],
            label="implementation Repair result manifest",
        )
        if result != _plain(request.result_manifest):
            raise EvidenceValidationError(
                "implementation Repair result request differs from its artifact"
            )
        if (
            set(plan) != _PLAN_FIELDS
            or plan.get("schema") != SEMANTIC_EQUIVALENCE_PLAN_SCHEMA
            or plan.get("protocol") != self.protocol
            or plan.get("validator_id") != self.validator_id
            or plan.get("job_id") != request.job_id
            or plan.get("job_hash") != request.job_hash
            or plan.get("executable_id")
            != request.evidence_subject.get("id")
            or request.evidence_subject.get("kind") != "Executable"
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
                "implementation Repair validation plan differs from its request"
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
                "implementation Repair semantic surface inventory is invalid"
            )
        for item in inventory:
            if (
                not isinstance(item, dict)
                or set(item)
                != {"category", "path", "surface_id", "value_hash"}
                or item.get("category") not in _SURFACE_CATEGORIES
            ):
                raise EvidenceValidationError(
                    "implementation Repair semantic surface entry is invalid"
                )

        old_identity = binding.get("old_implementation_identity")
        new_identity = binding.get("new_implementation_identity")
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
                "implementation Repair old/new identity binding is invalid"
            )
        old_manifest = _canonical_document(
            opened[old_identity], label="old implementation manifest"
        )
        new_manifest = _canonical_document(
            opened[new_identity], label="new implementation manifest"
        )
        for manifest, identity, artifact_field in (
            (
                old_manifest,
                old_identity,
                "old_implementation_artifact_hashes",
            ),
            (
                new_manifest,
                new_identity,
                "new_implementation_artifact_hashes",
            ),
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
                    "implementation Repair manifest or artifact set is invalid"
                )
        if (
            old_manifest.get("callable_identity")
            != new_manifest.get("callable_identity")
            or old_manifest.get("protocol") != new_manifest.get("protocol")
        ):
            raise EvidenceValidationError(
                "implementation Repair changes callable or protocol semantics"
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
            old_closure, old_paths, old_non_source_artifacts = _source_closure(
                implementation_manifest=old_manifest,
                opened=opened,
                label="old",
            )
            new_closure, new_paths, new_non_source_artifacts = _source_closure(
                implementation_manifest=new_manifest,
                opened=opened,
                label="new",
            )
            if old_non_source_artifacts != new_non_source_artifacts:
                raise RepairSemanticEquivalenceError(
                    "implementation Repair changes the exact non-source artifact closure"
                )
            (
                source_path_bindings,
                expected_changed_pairs,
                source_inventory_hash,
            ) = _source_path_comparison(
                old_paths=old_paths,
                new_paths=new_paths,
            )
            source_observation_risks = _source_observation_risks(
                old_paths=old_paths,
                new_paths=new_paths,
                opened=opened,
            )
        except RepairSemanticEquivalenceError as exc:
            raise EvidenceValidationError(
                "implementation Repair source-closure authority is invalid"
            ) from exc
        if (
            old_closure != plan.get("old_source_closure_hash")
            or old_closure != binding.get("old_source_closure_hash")
            or new_closure != plan.get("new_source_closure_hash")
            or new_closure != binding.get("new_source_closure_hash")
            or source_inventory_hash
            != plan.get("source_path_inventory_hash")
            or source_inventory_hash
            != binding.get("source_path_inventory_hash")
            or expected_changed_pairs
            != plan.get("changed_source_pair_bindings")
            or expected_changed_pairs
            != binding.get("changed_source_pair_bindings")
        ):
            raise EvidenceValidationError(
                "implementation Repair source paths differ from the exact plan"
            )

        measurement_hashes = binding.get("measurement_artifact_hashes")
        if (
            not isinstance(measurement_hashes, list)
            or measurement_hashes != sorted(set(measurement_hashes))
            or any(identity not in opened for identity in measurement_hashes)
        ):
            raise EvidenceValidationError(
                "implementation Repair measurement set is invalid"
            )
        expected_by_path = {
            pair["relative_path"]: pair for pair in expected_changed_pairs
        }
        measured_paths: set[str] = set()
        for identity in measurement_hashes:
            measurement = _canonical_document(
                opened[identity],
                label="implementation Repair semantic measurement",
            )
            if (
                set(measurement) != _MEASUREMENT_FIELDS
                or measurement.get("schema")
                != SEMANTIC_EQUIVALENCE_MEASUREMENT_SCHEMA
                or measurement.get("validation_plan_hash")
                != request.validation_plan_hash
                or measurement.get("method")
                != PYTHON_AST_EQUIVALENCE_METHOD
            ):
                raise EvidenceValidationError(
                    "implementation Repair semantic measurement is invalid"
                )
            old_artifact = measurement.get("old_artifact_hash")
            new_artifact = measurement.get("new_artifact_hash")
            relative_path = measurement.get("relative_path")
            expected_pair = expected_by_path.get(relative_path)
            if (
                expected_pair is None
                or relative_path in measured_paths
                or old_artifact != expected_pair["old_artifact_hash"]
                or new_artifact != expected_pair["new_artifact_hash"]
            ):
                raise EvidenceValidationError(
                    "implementation Repair measurement does not bind the exact "
                    "changed source path"
                )
            measured_paths.add(relative_path)

        implementation_protocol = old_manifest.get("protocol")
        python_protocol = (
            type(implementation_protocol) is str
            and implementation_protocol.startswith("python.")
        )
        python_source_paths = all(
            PurePosixPath(pair["relative_path"]).suffix == ".py"
            for pair in expected_changed_pairs
        )
        old_ast_hashes = {
            pair["relative_path"]: (
                _python_ast_sha256(opened[pair["old_artifact_hash"]])
                if python_protocol
                else None
            )
            for pair in expected_changed_pairs
        }
        new_ast_hashes = {
            pair["relative_path"]: (
                _python_ast_sha256(opened[pair["new_artifact_hash"]])
                if python_protocol
                else None
            )
            for pair in expected_changed_pairs
        }
        complete_pairing = (
            bool(expected_changed_pairs)
            and measured_paths == set(expected_by_path)
            and len(measurement_hashes) == len(expected_changed_pairs)
        )
        if not python_protocol:
            pairing_status = "non_python"
            verdict = "not_evaluable"
        elif not expected_changed_pairs:
            pairing_status = "no_changed_source_path"
            verdict = "not_evaluable"
        elif not complete_pairing:
            pairing_status = "missing_pair"
            verdict = "not_evaluable"
        elif not python_source_paths:
            pairing_status = "non_python_source_path"
            verdict = "not_evaluable"
        elif any(value is None for value in old_ast_hashes.values()) or any(
            value is None for value in new_ast_hashes.values()
        ):
            pairing_status = "unparseable_python"
            verdict = "not_evaluable"
        elif any(
            old_ast_hashes[path] != new_ast_hashes[path]
            for path in sorted(old_ast_hashes)
        ):
            pairing_status = "semantic_change"
            verdict = "failed"
        elif source_observation_risks:
            pairing_status = "source_observation_unproven"
            verdict = "not_evaluable"
        else:
            pairing_status = "passed"
            verdict = "passed"

        surface_results = [
            {
                "surface_id": surface_id,
                "verdict": verdict,
            }
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
            "verdict": verdict,
        }
        if set(result) != _RESULT_FIELDS or result != expected_result:
            raise EvidenceValidationError(
                "implementation Repair result was not independently reproduced"
            )
        passed_claims = tuple(claims) if verdict == "passed" else ()
        pair_facts = [
            {
                "equivalent": (
                    old_ast_hashes[pair["relative_path"]] is not None
                    and old_ast_hashes[pair["relative_path"]]
                    == new_ast_hashes[pair["relative_path"]]
                ),
                "new_artifact_hash": pair["new_artifact_hash"],
                "new_ast_sha256": new_ast_hashes[pair["relative_path"]],
                "old_artifact_hash": pair["old_artifact_hash"],
                "old_ast_sha256": old_ast_hashes[pair["relative_path"]],
                "relative_path": pair["relative_path"],
            }
            for pair in expected_changed_pairs
        ]
        return ValidatedEvidence(
            verdict=verdict,
            claims=passed_claims,
            measurement_artifact_hashes=tuple(measurement_hashes),
            facts={
                "added_artifact_hashes": list(added_artifacts),
                "artifact_equivalence_method": (
                    PYTHON_AST_EQUIVALENCE_METHOD
                ),
                "changed_source_pair_results": pair_facts,
                "covered_surface_ids": (
                    list(claims) if verdict == "passed" else []
                ),
                "new_implementation_artifact_hashes": list(new_artifacts),
                "new_implementation_identity": new_identity,
                "new_source_closure_hash": new_closure,
                "old_implementation_artifact_hashes": list(old_artifacts),
                "old_implementation_identity": old_identity,
                "old_source_closure_hash": old_closure,
                "pairing_status": pairing_status,
                "removed_artifact_hashes": list(removed_artifacts),
                "repair_id": plan["repair_id"],
                "result_manifest_hash": result_hash,
                "schema": SEMANTIC_EQUIVALENCE_FACTS_SCHEMA,
                "surface_inventory_hash": plan["surface_inventory_hash"],
                "source_path_bindings": source_path_bindings,
                "source_path_inventory_hash": source_inventory_hash,
                "source_observation_risks": list(
                    source_observation_risks
                ),
                "source_observation_scan_method": (
                    PYTHON_SOURCE_OBSERVATION_SCAN_METHOD
                ),
                "unchanged_artifact_hashes": list(unchanged_artifacts),
                "validation_plan_hash": request.validation_plan_hash,
            },
            scientific_eligible=False,
            candidate_eligible=False,
            release_eligible=False,
        )


__all__ = [
    "IMPLEMENTATION_REPAIR_V2_SCHEMA",
    "ImplementationRepairSemanticEquivalenceValidator",
    "PYTHON_AST_EQUIVALENCE_METHOD",
    "PYTHON_SOURCE_OBSERVATION_SCAN_METHOD",
    "RepairSemanticEquivalenceError",
    "SEMANTIC_EQUIVALENCE_BINDING_SCHEMA",
    "SEMANTIC_EQUIVALENCE_FACTS_SCHEMA",
    "SEMANTIC_EQUIVALENCE_MEASUREMENT_SCHEMA",
    "SEMANTIC_EQUIVALENCE_PLAN_SCHEMA",
    "SEMANTIC_EQUIVALENCE_PROTOCOL",
    "SEMANTIC_EQUIVALENCE_RESULT_SCHEMA",
    "SEMANTIC_EQUIVALENCE_VALIDATOR_DEPENDENCIES",
    "SEMANTIC_EQUIVALENCE_VALIDATOR_ID",
    "build_semantic_equivalence_binding",
    "build_semantic_equivalence_plan",
    "derive_semantic_surface_inventory",
    "require_passed_semantic_equivalence_facts",
    "semantic_equivalence_measurement",
    "semantic_equivalence_result_manifest",
]
