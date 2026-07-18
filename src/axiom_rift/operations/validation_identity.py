"""Stable semantic identity primitives shared by evidence validators.

Validator registration and Repair dispatch live in ``operations.validation``.
This module contains only the byte-sensitive primitives that can change a
validator identity embedded in scientific plans and results.  Scientific Job
source closures can therefore bind these semantics without inheriting
unrelated registry growth.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.validation_semantic_dependencies import (
    SemanticDependencyError,
    semantic_dependency_binding,
)


_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class EvidenceValidationError(RuntimeError):
    """Evidence could not be derived by a registered validator."""

    def __init__(self, message: str, *, reason_code: str | None = None) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise EvidenceValidationError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise EvidenceValidationError(
            f"{name} must be a lowercase SHA-256 digest"
        )
    return text


def validator_implementation_sha256(
    *,
    implementation_path: str | Path,
    dependency_paths: tuple[str | Path, ...] = (),
    semantic_boundary_paths: tuple[str | Path, ...] = (),
) -> str:
    """Bind implementation bytes and the authored semantic dependency closure.

    An implementation without authored semantic roots retains the legacy file
    digest.  Once roots are declared, project-local imports reached from those
    roots are identity-bearing even after a process restart.  Imports reached
    only from the implementation remain operational registry closure.
    """

    if type(dependency_paths) is not tuple:
        raise EvidenceValidationError(
            "validator dependency paths must be a declared tuple"
        )
    if type(semantic_boundary_paths) is not tuple:
        raise EvidenceValidationError(
            "validator semantic boundary paths must be a declared tuple"
        )

    def regular_file(value: str | Path, *, label: str) -> Path:
        try:
            raw = Path(value)
            if raw.is_symlink():
                raise EvidenceValidationError(f"{label} must not be a symlink")
            path = raw.resolve(strict=True)
        except (OSError, TypeError, ValueError) as exc:
            raise EvidenceValidationError(
                f"{label} is invalid or absent"
            ) from exc
        if not path.is_file():
            raise EvidenceValidationError(f"{label} must be a regular file")
        return path

    implementation = regular_file(
        implementation_path,
        label="validator implementation",
    )
    dependencies = tuple(
        regular_file(item, label="validator dependency")
        for item in dependency_paths
    )
    semantic_boundaries = tuple(
        regular_file(item, label="validator semantic boundary")
        for item in semantic_boundary_paths
    )
    if (
        len(set(dependencies)) != len(dependencies)
        or implementation in dependencies
    ):
        raise EvidenceValidationError(
            "validator dependency paths must be unique"
        )
    if (
        len(set(semantic_boundaries)) != len(semantic_boundaries)
        or implementation in semantic_boundaries
        or set(dependencies).intersection(semantic_boundaries)
    ):
        raise EvidenceValidationError(
            "validator semantic boundary paths must be unique and disjoint"
        )
    semantic_boundary_project_paths: list[str] = []
    for boundary in semantic_boundaries:
        try:
            project_path = boundary.relative_to(_PROJECT_ROOT).as_posix()
        except ValueError as exc:
            raise EvidenceValidationError(
                "validator semantic boundary must be project-local"
            ) from exc
        semantic_boundary_project_paths.append(project_path)

    def content_digest(path: Path, *, dependency: bool) -> str:
        try:
            content = path.read_bytes()
        except OSError as exc:
            label = "dependency" if dependency else "implementation"
            raise EvidenceValidationError(
                f"validator {label} file is absent"
            ) from exc
        return sha256(content).hexdigest()

    implementation_digest = content_digest(implementation, dependency=False)
    if not dependencies:
        return implementation_digest
    try:
        semantic_closure = semantic_dependency_binding(
            dependencies,
            boundary_paths=(implementation, *semantic_boundaries),
        )
    except SemanticDependencyError as exc:
        raise EvidenceValidationError(str(exc)) from exc
    by_path = {item.path: item for item in semantic_closure}
    if any(dependency not in by_path for dependency in dependencies):
        raise EvidenceValidationError(
            "validator semantic dependency closure is incomplete"
        )
    authored_dependencies = []
    for ordinal, dependency in enumerate(dependencies):
        item = by_path[dependency]
        entry: dict[str, object] = {
            "role": f"authored:{ordinal:04d}",
            "sha256": item.sha256,
        }
        if item.project_path is not None:
            entry["project_path"] = item.project_path
        authored_dependencies.append(entry)
    authored_paths = set(dependencies)
    transitive_dependencies = [
        {
            "project_path": item.project_path,
            "sha256": item.sha256,
        }
        for item in semantic_closure
        if item.path not in authored_paths and item.project_path is not None
    ]
    payload: dict[str, object] = {
        "authored_semantic_dependencies": authored_dependencies,
        "implementation_sha256": implementation_digest,
        "schema": "evidence_validator_implementation_bundle.v2",
        "semantic_transitive_dependencies": transitive_dependencies,
    }
    if semantic_boundaries:
        payload["schema"] = "evidence_validator_implementation_bundle.v3"
        payload["semantic_boundary_paths"] = semantic_boundary_project_paths
    return canonical_digest(
        domain="evidence-validator-implementation-bundle",
        payload=payload,
    )


def validator_identity(
    *,
    protocol: str,
    domains: frozenset[str],
    implementation_sha256: str,
) -> str:
    _ascii("validator protocol", protocol)
    _digest("validator implementation", implementation_sha256)
    return "validator:" + canonical_digest(
        domain="evidence-validator",
        payload={
            "domains": sorted(domains),
            "implementation_sha256": implementation_sha256,
            "protocol": protocol,
        },
    )


__all__ = [
    "EvidenceValidationError",
    "validator_identity",
    "validator_implementation_sha256",
]
