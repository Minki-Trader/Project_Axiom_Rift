"""Read-only verification for exact reusable Job success outputs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any


class JobCacheAuthorityError(RuntimeError):
    """A recorded Job success is not reusable from its current exact bytes."""


def require_cached_success_binding(
    *,
    cached_payload: Mapping[str, Any],
    completion_status: str,
    completion_payload: Mapping[str, Any],
    spec: Mapping[str, Any],
    mission_id: str,
    candidate_execution_context: Mapping[str, Any] | None,
    observed_development_binding: Mapping[str, Any] | None,
    implementation_source_authority: Mapping[str, Any] | None,
    external_observed_development_binding: Mapping[str, Any] | None,
) -> None:
    """Cross-bind one cache row to its exact completion and authority inputs."""

    if (
        completion_status != "success"
        or set(completion_payload.get("outputs", {}))
        != set(spec["expected_outputs"])
        or completion_payload.get("output_classes") != spec["output_classes"]
        or cached_payload.get("mission_id") != mission_id
        or cached_payload.get("candidate_execution_context")
        != candidate_execution_context
        or cached_payload.get("observed_development_binding")
        != observed_development_binding
        or cached_payload.get("implementation_source_authority")
        != implementation_source_authority
        or cached_payload.get("external_observed_development_binding")
        != external_observed_development_binding
    ):
        raise JobCacheAuthorityError("successful Job cache is inconsistent")


def _require_digest(name: str, value: object) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise JobCacheAuthorityError(
            f"{name} must be a lowercase SHA-256 digest"
        )
    return value


def require_reusable_success_outputs(
    *,
    completion_payload: Mapping[str, Any],
    spec: Mapping[str, Any],
    repository_root: Path,
    durable_verifier: Callable[[str], object],
) -> None:
    """Open every reusable output under its declared storage-class policy."""

    outputs = completion_payload.get("outputs")
    output_classes = spec["output_classes"]
    if not isinstance(outputs, dict):
        raise JobCacheAuthorityError(
            "successful Job cache has no output manifest"
        )
    for output_name in spec["expected_outputs"]:
        output_hash = outputs.get(output_name)
        try:
            digest = _require_digest("cached output hash", output_hash)
            output_class = output_classes[output_name]
            if output_class == "durable_evidence":
                durable_verifier(digest)
                continue
            if output_class == "transient":
                raise JobCacheAuthorityError(
                    "successful Job cache cannot reuse transient output"
                )
            target = (repository_root / output_name).resolve()
            cache_root = (repository_root / "local" / "cache").resolve()
            if cache_root not in target.parents or not target.is_file():
                raise JobCacheAuthorityError(
                    "successful Job cache output is unavailable"
                )
            if sha256(target.read_bytes()).hexdigest() != digest:
                raise JobCacheAuthorityError(
                    "successful Job cache output hash mismatch"
                )
        except JobCacheAuthorityError:
            raise
        except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
            raise JobCacheAuthorityError(
                "successful Job cache output is unavailable or corrupt"
            ) from exc


__all__ = [
    "JobCacheAuthorityError",
    "require_cached_success_binding",
    "require_reusable_success_outputs",
]
