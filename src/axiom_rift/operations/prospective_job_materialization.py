"""Materialize current-source authority for a prospective Python Job.

This module runs outside the Job engine.  Keeping source discovery and evidence
publication here prevents a scientific callable from importing management-only
dependency-path capabilities merely to prove its own implementation bytes.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.operations.running_job_context import (
    running_job_operational_identity_boundary_paths,
    running_job_scientific_projection_dependency_paths,
)
from axiom_rift.operations.validation import validator_execution_dependency_paths


def prospective_job_dependency_paths(entry_path: Path) -> tuple[Path, ...]:
    """Infer the exact recursive Job closure without importing this helper."""

    if not isinstance(entry_path, Path) or not entry_path.is_file():
        raise ValueError("prospective Job entry path is unavailable")
    paths = set(
        validator_execution_dependency_paths(
            entry_path,
            running_job_scientific_projection_dependency_paths(),
        )
    )
    paths.difference_update(running_job_operational_identity_boundary_paths())
    return tuple(sorted(paths, key=lambda path: path.as_posix()))


def prospective_job_source_closure_artifact(
    *,
    callable_identity: str,
    dependency_paths: tuple[Path, ...],
    source_root: Path,
) -> bytes:
    if type(callable_identity) is not str or not callable_identity.isascii():
        raise ValueError("prospective Job callable identity is invalid")
    dependencies: list[dict[str, str]] = []
    for path in dependency_paths:
        if not path.is_file():
            raise RuntimeError("prospective Job dependency is unavailable")
        try:
            relative = path.relative_to(source_root).as_posix()
        except ValueError as exc:
            raise RuntimeError(
                "prospective Job dependency is outside the source root"
            ) from exc
        dependencies.append(
            {"path": relative, "sha256": sha256(path.read_bytes()).hexdigest()}
        )
    dependencies.sort(key=lambda item: item["path"])
    if not dependencies or len({item["path"] for item in dependencies}) != len(
        dependencies
    ):
        raise RuntimeError("prospective Job dependency closure is invalid")
    return canonical_bytes(
        {
            "callable_identity": callable_identity,
            "dependencies": dependencies,
            "schema": "job_implementation_source_closure.v1",
        }
    )


def prospective_job_implementation_artifact(
    *,
    callable_identity: str,
    protocol: str,
    dependency_paths: tuple[Path, ...],
    source_root: Path,
) -> bytes:
    if type(protocol) is not str or not protocol or not protocol.isascii():
        raise ValueError("prospective Job implementation protocol is invalid")
    closure = prospective_job_source_closure_artifact(
        callable_identity=callable_identity,
        dependency_paths=dependency_paths,
        source_root=source_root,
    )
    return canonical_bytes(
        {
            "artifact_hashes": sorted(
                {
                    sha256(closure).hexdigest(),
                    *(
                        sha256(path.read_bytes()).hexdigest()
                        for path in dependency_paths
                    ),
                }
            ),
            "callable_identity": callable_identity,
            "protocol": protocol,
            "schema": "job_implementation_evidence.v1",
        }
    )


def prospective_job_implementation_sha256(
    *,
    entry_path: Path,
    callable_identity: str,
    protocol: str,
    source_root: Path,
) -> str:
    paths = prospective_job_dependency_paths(entry_path)
    return sha256(
        prospective_job_implementation_artifact(
            callable_identity=callable_identity,
            protocol=protocol,
            dependency_paths=paths,
            source_root=source_root,
        )
    ).hexdigest()


def materialize_prospective_job_implementation(
    writer: Any,
    *,
    entry_path: Path,
    callable_identity: str,
    protocol: str,
    source_root: Path,
) -> str:
    """Store every current source byte, one closure, and one implementation."""

    paths = prospective_job_dependency_paths(entry_path)
    for path in paths:
        content = path.read_bytes()
        artifact = writer.evidence.finalize(content)
        if artifact.sha256 != sha256(content).hexdigest():
            raise RuntimeError("prospective Job source identity drifted")
    closure = prospective_job_source_closure_artifact(
        callable_identity=callable_identity,
        dependency_paths=paths,
        source_root=source_root,
    )
    if writer.evidence.finalize(closure).sha256 != sha256(closure).hexdigest():
        raise RuntimeError("prospective Job source closure identity drifted")
    manifest = prospective_job_implementation_artifact(
        callable_identity=callable_identity,
        protocol=protocol,
        dependency_paths=paths,
        source_root=source_root,
    )
    implementation = writer.evidence.finalize(manifest)
    if implementation.sha256 != sha256(manifest).hexdigest():
        raise RuntimeError("prospective Job implementation identity drifted")
    return implementation.sha256


__all__ = [
    "materialize_prospective_job_implementation",
    "prospective_job_dependency_paths",
    "prospective_job_implementation_artifact",
    "prospective_job_implementation_sha256",
    "prospective_job_source_closure_artifact",
]
