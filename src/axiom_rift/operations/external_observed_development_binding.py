"""Prospective Job authority for external observed-development prefixes.

The registered Executable manifest is the source-consumption declaration.  A
Job that targets such an Executable must name both the exact material identity
and the exact prefix SHA-256.  Durable bindings are recomputed against the
current registry at Job start or cached-success reuse; physical verification
opens only the materialized prefix and never its quarantined raw parent.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from axiom_rift.core.identity import canonical_digest
from axiom_rift.research.external_observed_development import (
    ExternalObservedDevelopmentError,
    ProspectiveExternalSourceJobBinding,
    US30_OBSERVED_DEVELOPMENT_SPEC,
    US500_OBSERVED_DEVELOPMENT_SPEC,
    USDJPY_OBSERVED_DEVELOPMENT_SPEC,
    external_observed_development_loader_implementation_sha256,
    external_observed_development_spec,
    prospective_external_source_job_binding,
    verify_external_observed_development_prefix_identity,
)


_EXECUTABLE_SCHEMA = "executable_spec.v1"
_BINDING_SCHEMA = "external_observed_development_job_binding.v1"
_COMPONENT_MARKERS = frozenset(
    {
        "development_source_key",
        "development_material_identity",
        "development_prefix_sha256",
        "development_prefix_byte_count",
        "development_prefix_row_count",
        "development_loader_implementation_sha256",
    }
)
_REQUIRED_COMPONENT_FIELDS = _COMPONENT_MARKERS | {
    "raw_sha256",
    "raw_sha256_role",
}
_KNOWN_RAW_SHA256 = frozenset(
    {
        US30_OBSERVED_DEVELOPMENT_SPEC.parent_raw_sha256,
        US500_OBSERVED_DEVELOPMENT_SPEC.parent_raw_sha256,
        USDJPY_OBSERVED_DEVELOPMENT_SPEC.parent_raw_sha256,
    }
)
_LOADER_SOURCE_PATH = "axiom_rift/research/external_observed_development.py"


class ExternalObservedDevelopmentJobBindingError(ValueError):
    """A prospective external-source Job is incompletely or falsely bound."""


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ExternalObservedDevelopmentJobBindingError(f"{name} must be a mapping")
    return value


def _ascii(value: object, name: str) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ExternalObservedDevelopmentJobBindingError(
            f"{name} must be non-empty ASCII"
        )
    return value


def _digest(value: object, name: str) -> str:
    digest = _ascii(value, name)
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ExternalObservedDevelopmentJobBindingError(
            f"{name} must be a lowercase SHA-256 digest"
        )
    return digest


def _executable_id(value: object, name: str) -> str:
    executable_id = _ascii(value, name)
    digest = executable_id.removeprefix("executable:")
    if not executable_id.startswith("executable:"):
        raise ExternalObservedDevelopmentJobBindingError(
            f"{name} must be an Executable identity"
        )
    _digest(digest, name)
    return executable_id


@dataclass(frozen=True, slots=True)
class ExternalObservedDevelopmentJobBinding:
    """Exact external prefix set consumed by one registered Executable Job."""

    executable_id: str
    source_bindings: tuple[ProspectiveExternalSourceJobBinding, ...]

    def __post_init__(self) -> None:
        _executable_id(self.executable_id, "binding Executable identity")
        keys = tuple(binding.source_key for binding in self.source_bindings)
        if not keys or keys != tuple(sorted(set(keys))):
            raise ExternalObservedDevelopmentJobBindingError(
                "external source bindings must be non-empty, sorted, and unique"
            )

    def to_payload(self) -> dict[str, object]:
        return {
            "executable_id": self.executable_id,
            "schema": _BINDING_SCHEMA,
            "source_bindings": [
                binding.to_payload() for binding in self.source_bindings
            ],
        }


def _validate_manifest_identity(
    executable_id: str,
    executable_manifest: Mapping[str, Any],
) -> None:
    if executable_manifest.get("schema") != _EXECUTABLE_SCHEMA:
        raise ExternalObservedDevelopmentJobBindingError(
            "Executable manifest schema is invalid"
        )
    try:
        expected = "executable:" + canonical_digest(
            domain="executable", payload=dict(executable_manifest)
        )
    except (TypeError, ValueError) as exc:
        raise ExternalObservedDevelopmentJobBindingError(
            "Executable manifest is not canonical"
        ) from exc
    if expected != executable_id:
        raise ExternalObservedDevelopmentJobBindingError(
            "Executable manifest differs from its identity"
        )


def _component_source_keys(
    executable_manifest: Mapping[str, Any],
) -> tuple[str, ...]:
    components = executable_manifest.get("component_manifests")
    if not isinstance(components, list) or not components:
        raise ExternalObservedDevelopmentJobBindingError(
            "Executable component manifests are absent"
        )
    loader_sha256 = external_observed_development_loader_implementation_sha256()
    source_keys: list[str] = []
    for index, value in enumerate(components):
        component = _mapping(value, f"Executable component {index}")
        specification = _mapping(
            component.get("spec"), f"Executable component {index} specification"
        )
        raw_claim = specification.get("raw_sha256") in _KNOWN_RAW_SHA256
        marker_claim = any(name in specification for name in _COMPONENT_MARKERS)
        if not raw_claim and not marker_claim:
            continue
        missing = sorted(_REQUIRED_COMPONENT_FIELDS - set(specification))
        if missing:
            raise ExternalObservedDevelopmentJobBindingError(
                "external source component omits exact observed-development fields: "
                + ", ".join(missing)
            )
        source_key = _ascii(
            specification.get("development_source_key"),
            "external development source key",
        )
        try:
            registered = external_observed_development_spec(source_key)
        except ExternalObservedDevelopmentError as exc:
            raise ExternalObservedDevelopmentJobBindingError(
                "external source component names an unknown development source"
            ) from exc
        expected = {
            "development_loader_implementation_sha256": loader_sha256,
            "development_material_identity": registered.material_identity,
            "development_prefix_byte_count": registered.prefix_byte_count,
            "development_prefix_row_count": registered.row_count,
            "development_prefix_sha256": registered.prefix_sha256,
            "development_source_key": registered.source_key,
            "raw_sha256": registered.parent_raw_sha256,
            "raw_sha256_role": "acquisition_identity_only",
        }
        if any(
            specification.get(name) != expected_value
            for name, expected_value in expected.items()
        ):
            raise ExternalObservedDevelopmentJobBindingError(
                f"{source_key} component differs from the current external prefix registry"
            )
        source_keys.append(source_key)
    if len(source_keys) != len(set(source_keys)):
        raise ExternalObservedDevelopmentJobBindingError(
            "Executable declares a duplicate external development source"
        )
    return tuple(sorted(source_keys))


def _source_closure_uses_external_loader(
    dependencies: Sequence[Mapping[str, Any]],
) -> bool:
    if isinstance(dependencies, (str, bytes)):
        raise ExternalObservedDevelopmentJobBindingError(
            "Job source closure dependencies must be a sequence of mappings"
        )
    normalized: list[tuple[str, str]] = []
    for index, value in enumerate(dependencies):
        dependency = _mapping(value, f"Job source closure dependency {index}")
        if set(dependency) != {"path", "sha256"}:
            raise ExternalObservedDevelopmentJobBindingError(
                "Job source closure dependency fields are invalid"
            )
        normalized.append(
            (
                _ascii(dependency.get("path"), "Job source closure dependency path"),
                _digest(
                    dependency.get("sha256"),
                    "Job source closure dependency SHA-256",
                ),
            )
        )
    paths = tuple(path for path, _ in normalized)
    if len(paths) != len(set(paths)):
        raise ExternalObservedDevelopmentJobBindingError(
            "Job source closure contains duplicate paths"
        )
    loader_dependencies = tuple(
        digest for path, digest in normalized if path == _LOADER_SOURCE_PATH
    )
    if not loader_dependencies:
        return False
    if loader_dependencies != (
        external_observed_development_loader_implementation_sha256(),
    ):
        raise ExternalObservedDevelopmentJobBindingError(
            "Job source closure external loader hash differs from current bytes"
        )
    return True


def _require_manifest_closure(
    executable_manifest: Mapping[str, Any],
    source_keys: tuple[str, ...],
) -> None:
    parameters = _mapping(
        executable_manifest.get("parameters"), "Executable parameters"
    )
    engine_contract = _ascii(
        executable_manifest.get("engine_contract"), "Executable engine contract"
    )
    parameter_markers = (
        "source_development_material_identity" in parameters
        or "source_development_prefix_sha256" in parameters
    )
    engine_markers = (
        "external_loader_" in engine_contract
        or "external_development_" in engine_contract
        or "development_prefix_" in engine_contract
    )
    if not source_keys:
        if parameter_markers or engine_markers:
            raise ExternalObservedDevelopmentJobBindingError(
                "Executable claims external development consumption without "
                "an exact component manifest"
            )
        return
    loader_sha256 = external_observed_development_loader_implementation_sha256()
    for source_key in source_keys:
        registered = external_observed_development_spec(source_key)
        for required in (
            registered.material_identity,
            registered.prefix_sha256,
            loader_sha256,
        ):
            if required not in engine_contract:
                raise ExternalObservedDevelopmentJobBindingError(
                    f"{source_key} engine contract omits an external prefix identity"
                )
    if parameter_markers:
        material = parameters.get("source_development_material_identity")
        prefix = parameters.get("source_development_prefix_sha256")
        if not any(
            material == external_observed_development_spec(key).material_identity
            and prefix == external_observed_development_spec(key).prefix_sha256
            for key in source_keys
        ):
            raise ExternalObservedDevelopmentJobBindingError(
                "Executable parameter-level external prefix binding differs"
            )


def external_observed_development_job_input_hashes(
    *,
    executable_manifest: Mapping[str, Any],
    source_closure_dependencies: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Derive exact sorted Job inputs for a prospective external Executable.

    Portfolio and Job builders call this before declaration and merge the
    returned hashes with their other immutable inputs.  The Writer validates;
    it never repairs or silently appends omitted inputs.
    """

    manifest = _mapping(executable_manifest, "Executable manifest")
    if manifest.get("schema") != _EXECUTABLE_SCHEMA:
        raise ExternalObservedDevelopmentJobBindingError(
            "Executable manifest schema is invalid"
        )
    source_keys = _component_source_keys(manifest)
    _require_manifest_closure(manifest, source_keys)
    source_closure_uses_loader = _source_closure_uses_external_loader(
        source_closure_dependencies
    )
    if bool(source_keys) != source_closure_uses_loader:
        raise ExternalObservedDevelopmentJobBindingError(
            "Executable external prefix manifest and implementation source closure disagree"
        )
    return tuple(
        sorted(
            {
                value
                for source_key in source_keys
                for value in external_observed_development_spec(
                    source_key
                ).job_input_hashes()
            }
        )
    )


def build_external_observed_development_job_spec(
    *,
    base_job_spec: Mapping[str, Any],
    executable_manifest: Mapping[str, Any],
    source_closure_dependencies: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return a caller-side Job spec with every exact external input merged.

    This is a Portfolio/runner builder, not Writer behavior.  It makes the
    prospective declaration explicit before the spec reaches StateWriter.
    """

    job_spec = dict(_mapping(base_job_spec, "base Job spec"))
    inputs = job_spec.get("input_hashes")
    if not isinstance(inputs, list) or not inputs:
        raise ExternalObservedDevelopmentJobBindingError(
            "base Job input hashes must be a non-empty list"
        )
    normalized = tuple(_digest(value, "base Job input hash") for value in inputs)
    if normalized != tuple(sorted(set(normalized))):
        raise ExternalObservedDevelopmentJobBindingError(
            "base Job input hashes must be sorted and unique"
        )
    required = external_observed_development_job_input_hashes(
        executable_manifest=executable_manifest,
        source_closure_dependencies=source_closure_dependencies,
    )
    job_spec["input_hashes"] = list(sorted({*normalized, *required}))
    return job_spec


def external_observed_development_job_binding(
    *,
    executable_id: str,
    executable_manifest: Mapping[str, Any],
    job_spec: Mapping[str, Any],
    source_closure_dependencies: Sequence[Mapping[str, Any]],
) -> ExternalObservedDevelopmentJobBinding | None:
    """Build the exact durable binding for one prospective Executable Job.

    Non-Executable Jobs and Executables with no external development claim are
    unaffected.  A partial claim, including a known raw acquisition hash with
    no prefix declaration, fails closed.
    """

    subject = job_spec.get("evidence_subject")
    if not isinstance(subject, Mapping) or subject.get("kind") != "Executable":
        return None
    normalized_id = _executable_id(executable_id, "Executable identity")
    if subject != {"kind": "Executable", "id": normalized_id}:
        raise ExternalObservedDevelopmentJobBindingError(
            "Job evidence subject differs from the supplied Executable"
        )
    manifest = _mapping(executable_manifest, "Executable manifest")
    _validate_manifest_identity(normalized_id, manifest)
    source_keys = _component_source_keys(manifest)
    _require_manifest_closure(manifest, source_keys)
    source_closure_uses_loader = _source_closure_uses_external_loader(
        source_closure_dependencies
    )
    if bool(source_keys) != source_closure_uses_loader:
        raise ExternalObservedDevelopmentJobBindingError(
            "Executable external prefix manifest and implementation source closure disagree"
        )
    if not source_keys:
        return None
    inputs = job_spec.get("input_hashes")
    if not isinstance(inputs, list):
        raise ExternalObservedDevelopmentJobBindingError(
            "Job input hashes must be a list"
        )
    bindings: list[ProspectiveExternalSourceJobBinding] = []
    for source_key in source_keys:
        try:
            bindings.append(
                prospective_external_source_job_binding(
                    source_key, input_hashes=tuple(inputs)
                )
            )
        except ExternalObservedDevelopmentError as exc:
            raise ExternalObservedDevelopmentJobBindingError(str(exc)) from exc
    return ExternalObservedDevelopmentJobBinding(
        executable_id=normalized_id,
        source_bindings=tuple(bindings),
    )


def verify_external_observed_development_job_prefixes(
    *,
    repository_root: str | Path,
    binding: ExternalObservedDevelopmentJobBinding,
) -> None:
    """Verify each bound materialized prefix exactly once, without raw access."""

    if not isinstance(binding, ExternalObservedDevelopmentJobBinding):
        raise TypeError("binding must be ExternalObservedDevelopmentJobBinding")
    for source_binding in binding.source_bindings:
        try:
            metadata = verify_external_observed_development_prefix_identity(
                repository_root, source_binding.source_key
            )
        except ExternalObservedDevelopmentError as exc:
            raise ExternalObservedDevelopmentJobBindingError(
                f"{source_binding.source_key} bound prefix is physically unavailable or invalid"
            ) from exc
        if (
            metadata.material_identity != source_binding.material_identity
            or metadata.development_prefix_sha256
            != source_binding.development_prefix_sha256
            or external_observed_development_loader_implementation_sha256()
            != source_binding.loader_implementation_sha256
        ):
            raise ExternalObservedDevelopmentJobBindingError(
                f"{source_binding.source_key} physical prefix binding differs"
            )


def require_current_external_observed_development_job_binding(
    *,
    executable_id: str,
    executable_manifest: Mapping[str, Any],
    job_spec: Mapping[str, Any],
    source_closure_dependencies: Sequence[Mapping[str, Any]],
    durable_payload: Mapping[str, Any] | None,
    repository_root: str | Path,
) -> ExternalObservedDevelopmentJobBinding | None:
    """Recompute a durable binding and verify its physical prefixes at start/reuse."""

    current = external_observed_development_job_binding(
        executable_id=executable_id,
        executable_manifest=executable_manifest,
        job_spec=job_spec,
        source_closure_dependencies=source_closure_dependencies,
    )
    expected_payload = None if current is None else current.to_payload()
    actual_payload = None if durable_payload is None else dict(durable_payload)
    if actual_payload != expected_payload:
        raise ExternalObservedDevelopmentJobBindingError(
            "durable external observed-development Job binding differs"
        )
    if current is not None:
        verify_external_observed_development_job_prefixes(
            repository_root=repository_root,
            binding=current,
        )
    return current


__all__ = [
    "build_external_observed_development_job_spec",
    "ExternalObservedDevelopmentJobBinding",
    "ExternalObservedDevelopmentJobBindingError",
    "external_observed_development_job_binding",
    "external_observed_development_job_input_hashes",
    "require_current_external_observed_development_job_binding",
    "verify_external_observed_development_job_prefixes",
]
