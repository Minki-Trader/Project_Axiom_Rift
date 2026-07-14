"""Prospective Component-to-Job implementation evidence closure."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from hashlib import sha256
from pathlib import Path
import re
from typing import Any

from axiom_rift.core.identity import (
    CANONICAL_IDENTITY_PREFIX,
    parse_canonical_identity_bytes,
)


_IMPLEMENTATION_REFERENCE = re.compile(
    r"^[A-Za-z0-9_./:-]+@sha256:([0-9a-f]{64})$"
)
COMPONENT_IMPLEMENTATION_BUNDLE_SCHEMA = "component_implementation_bundle.v1"
_BUNDLE_SCHEMA_FIELD = "implementation_bundle_schema"
_BUNDLE_DEPENDENCIES_FIELD = "dependency_artifact_hashes"


class ImplementationClosureError(ValueError):
    """Raised when prospective code identity is not closed by durable bytes."""


def semantic_dependency_closure(
    *,
    roots: tuple[Path, ...],
    dependency_graph: Mapping[Path, tuple[Path, ...]],
    source_root: Path,
) -> tuple[Path, ...]:
    """Return one deterministic, explicit project-source dependency closure.

    The graph is deliberately authored from executed semantic calls rather
    than inferred from every Python import.  Package initializers,
    ``TYPE_CHECKING`` imports, and unused compatibility imports therefore do
    not make unrelated edits reidentify a Component.  Every reachable node is
    still explicit, regular, local Python source and cycles fail closed.
    """

    if type(roots) is not tuple or not roots:
        raise ImplementationClosureError(
            "semantic dependency roots must be a non-empty tuple"
        )
    if not isinstance(dependency_graph, Mapping) or not dependency_graph:
        raise ImplementationClosureError(
            "semantic dependency graph must be a non-empty mapping"
        )
    if not isinstance(source_root, Path):
        raise ImplementationClosureError("semantic source root must be a Path")
    try:
        normalized_root = source_root.resolve(strict=True)
    except OSError as exc:
        raise ImplementationClosureError(
            "semantic source root is unavailable"
        ) from exc
    if not normalized_root.is_dir():
        raise ImplementationClosureError(
            "semantic source root must be a directory"
        )

    def normalize(value: object) -> Path:
        if not isinstance(value, Path):
            raise ImplementationClosureError(
                "semantic dependency nodes must be Paths"
            )
        if value.is_symlink():
            raise ImplementationClosureError(
                "semantic dependency source must not be a symlink"
            )
        try:
            resolved = value.resolve(strict=True)
        except OSError as exc:
            raise ImplementationClosureError(
                "semantic dependency source is unavailable"
            ) from exc
        if not resolved.is_file() or resolved.suffix != ".py":
            raise ImplementationClosureError(
                "semantic dependency source must be a regular Python file"
            )
        try:
            resolved.relative_to(normalized_root)
        except ValueError as exc:
            raise ImplementationClosureError(
                "semantic dependency source escapes the project source root"
            ) from exc
        return resolved

    normalized_graph: dict[Path, tuple[Path, ...]] = {}
    for raw_node, raw_dependencies in dependency_graph.items():
        node = normalize(raw_node)
        if node in normalized_graph:
            raise ImplementationClosureError(
                "semantic dependency graph contains duplicate source nodes"
            )
        if type(raw_dependencies) is not tuple:
            raise ImplementationClosureError(
                "semantic dependency edges must be tuples"
            )
        dependencies = tuple(normalize(value) for value in raw_dependencies)
        if len(set(dependencies)) != len(dependencies):
            raise ImplementationClosureError(
                "semantic dependency edges contain duplicates"
            )
        normalized_graph[node] = tuple(
            sorted(
                dependencies,
                key=lambda path: path.relative_to(
                    normalized_root
                ).as_posix(),
            )
        )

    normalized_roots = tuple(normalize(value) for value in roots)
    if len(set(normalized_roots)) != len(normalized_roots):
        raise ImplementationClosureError(
            "semantic dependency roots contain duplicates"
        )
    declared_nodes = set(normalized_graph)
    referenced_nodes = set(normalized_roots) | {
        dependency
        for dependencies in normalized_graph.values()
        for dependency in dependencies
    }
    missing_nodes = referenced_nodes.difference(declared_nodes)
    if missing_nodes:
        raise ImplementationClosureError(
            "semantic dependency graph omits explicit source nodes: "
            + ",".join(
                path.relative_to(normalized_root).as_posix()
                for path in sorted(
                    missing_nodes,
                    key=lambda item: item.relative_to(
                        normalized_root
                    ).as_posix(),
                )
            )
        )

    ordered: list[Path] = []
    visiting: set[Path] = set()
    visited: set[Path] = set()

    def visit(node: Path) -> None:
        if node in visiting:
            raise ImplementationClosureError(
                "semantic dependency graph contains a cycle"
            )
        if node in visited:
            return
        visiting.add(node)
        ordered.append(node)
        for dependency in normalized_graph[node]:
            visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for root in sorted(
        normalized_roots,
        key=lambda path: path.relative_to(normalized_root).as_posix(),
    ):
        visit(root)
    unreachable = declared_nodes.difference(visited)
    if unreachable:
        raise ImplementationClosureError(
            "semantic dependency graph contains unreachable source nodes: "
            + ",".join(
                path.relative_to(normalized_root).as_posix()
                for path in sorted(
                    unreachable,
                    key=lambda item: item.relative_to(
                        normalized_root
                    ).as_posix(),
                )
            )
        )
    return tuple(ordered)


def component_implementation_sha256(reference: object) -> str:
    """Return the direct artifact digest from one typed Component reference."""

    if type(reference) is not str or not reference.isascii():
        raise ImplementationClosureError(
            "component implementation reference must be ASCII text"
        )
    matched = _IMPLEMENTATION_REFERENCE.fullmatch(reference)
    if matched is None:
        raise ImplementationClosureError(
            "component implementation reference must end in @sha256:<digest>"
        )
    return matched.group(1)


def executable_implementation_hashes(
    executable_manifest: Mapping[str, Any],
) -> tuple[str, ...]:
    """Resolve the direct implementation artifacts declared by an Executable."""

    manifests = executable_manifest.get("component_manifests")
    identities = executable_manifest.get("component_identities")
    if (
        executable_manifest.get("schema") != "executable_spec.v1"
        or not isinstance(manifests, list)
        or not manifests
        or not isinstance(identities, list)
        or len(identities) != len(manifests)
    ):
        raise ImplementationClosureError("Executable component closure is malformed")
    hashes: set[str] = set()
    for manifest in manifests:
        if not isinstance(manifest, Mapping):
            raise ImplementationClosureError("Component manifest is malformed")
        hashes.add(component_implementation_sha256(manifest.get("implementation")))
    return tuple(sorted(hashes))


def _is_digest(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _bundle_dependencies(content: bytes) -> tuple[str, ...] | None:
    if not content.startswith(CANONICAL_IDENTITY_PREFIX):
        return None
    try:
        _, payload = parse_canonical_identity_bytes(content)
    except (TypeError, ValueError) as exc:
        raise ImplementationClosureError(
            "Component implementation identity frame is invalid"
        ) from exc
    if not isinstance(payload, Mapping):
        return None
    has_schema = _BUNDLE_SCHEMA_FIELD in payload
    has_dependencies = _BUNDLE_DEPENDENCIES_FIELD in payload
    if not has_schema and not has_dependencies:
        return None
    dependencies = payload.get(_BUNDLE_DEPENDENCIES_FIELD)
    if (
        not has_schema
        or not has_dependencies
        or payload.get(_BUNDLE_SCHEMA_FIELD)
        != COMPONENT_IMPLEMENTATION_BUNDLE_SCHEMA
        or not isinstance(dependencies, list)
        or not dependencies
        or any(not _is_digest(value) for value in dependencies)
        or dependencies != sorted(set(dependencies))
    ):
        raise ImplementationClosureError(
            "Component implementation bundle payload is invalid"
        )
    return tuple(dependencies)


def require_job_implementation_closure(
    *,
    executable_manifest: Mapping[str, Any],
    job_artifact_hashes: Sequence[str],
    artifact_reader: Callable[[str], bytes],
) -> tuple[str, ...]:
    """Verify direct Component bytes and every typed implementation bundle."""

    artifacts = tuple(job_artifact_hashes)
    if (
        not artifacts
        or any(not _is_digest(value) for value in artifacts)
        or len(set(artifacts)) != len(artifacts)
    ):
        raise ImplementationClosureError("Job implementation artifacts are malformed")
    if not callable(artifact_reader):
        raise ImplementationClosureError("artifact_reader must be callable")
    required = executable_implementation_hashes(executable_manifest)
    artifact_set = set(artifacts)
    missing = tuple(sorted(set(required).difference(artifact_set)))
    if missing:
        raise ImplementationClosureError(
            "Job implementation evidence omits Component source bytes: "
            + ",".join(missing)
        )

    verified: set[str] = set()
    active: set[str] = set()

    def verify_artifact(identity: str) -> None:
        if identity in active:
            raise ImplementationClosureError(
                "Component implementation bundle dependency cycle is invalid"
            )
        if identity in verified:
            return
        try:
            content = artifact_reader(identity)
        except Exception as exc:
            raise ImplementationClosureError(
                f"Component implementation artifact is unavailable: {identity}"
            ) from exc
        if type(content) is not bytes:
            raise ImplementationClosureError(
                "Component implementation artifact reader must return bytes"
            )
        if sha256(content).hexdigest() != identity:
            raise ImplementationClosureError(
                f"Component implementation artifact hash mismatch: {identity}"
            )
        active.add(identity)
        try:
            dependencies = _bundle_dependencies(content)
            if dependencies is not None:
                missing_dependencies = tuple(
                    sorted(set(dependencies).difference(artifact_set))
                )
                if missing_dependencies:
                    raise ImplementationClosureError(
                        "Job implementation evidence omits Component bundle "
                        "dependencies: " + ",".join(missing_dependencies)
                    )
                for dependency in dependencies:
                    verify_artifact(dependency)
        finally:
            active.remove(identity)
        verified.add(identity)

    for identity in required:
        verify_artifact(identity)
    return required


__all__ = [
    "ImplementationClosureError",
    "COMPONENT_IMPLEMENTATION_BUNDLE_SCHEMA",
    "component_implementation_sha256",
    "executable_implementation_hashes",
    "require_job_implementation_closure",
    "semantic_dependency_closure",
]
