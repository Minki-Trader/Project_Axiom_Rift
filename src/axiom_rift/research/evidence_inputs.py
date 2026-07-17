"""Typed, one-snapshot readers for declared research evidence inputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from axiom_rift.core.canonical import CanonicalJSONError, parse_canonical


class VerifiedEvidenceReader(Protocol):
    """Minimum capability accepted by research evidence-input readers."""

    def read_verified(self, identity: str) -> bytes: ...


def _ascii_schema(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ValueError(f"{name} must be non-empty ASCII")
    return value


def _sha256_digest(name: str, value: object) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True, slots=True)
class CanonicalEvidenceInput:
    """One verified content identity and its canonical object value."""

    artifact_sha256: str
    schema: str
    value: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ExactEvidenceInputs:
    """Exactly one verified canonical object for every requested schema."""

    declared_identities: tuple[str, ...]
    artifacts: tuple[CanonicalEvidenceInput, ...]

    def require(self, schema: str) -> CanonicalEvidenceInput:
        expected = _ascii_schema("evidence schema", schema)
        for artifact in self.artifacts:
            if artifact.schema == expected:
                return artifact
        raise ValueError(f"required evidence schema is absent: {expected}")


@dataclass(frozen=True, slots=True)
class BoundEvidenceInputs:
    """Exact identity-bound canonical evidence consumed by one Job."""

    declared_identities: tuple[str, ...]
    artifacts: tuple[CanonicalEvidenceInput, ...]

    def require_identity(self, identity: str) -> CanonicalEvidenceInput:
        expected = _sha256_digest("evidence artifact identity", identity)
        for artifact in self.artifacts:
            if artifact.artifact_sha256 == expected:
                return artifact
        raise ValueError(f"required evidence identity is absent: {expected}")


@dataclass(frozen=True, slots=True)
class SurfaceManifestEvidenceInputs:
    """One surface and one manifest bound to that exact surface identity."""

    surface: CanonicalEvidenceInput
    manifest: CanonicalEvidenceInput


def read_exact_evidence_inputs(
    store: VerifiedEvidenceReader,
    identities: tuple[str, ...],
    *,
    required_schemas: tuple[str, ...],
) -> ExactEvidenceInputs:
    """Read each unique declared hash once and resolve exact schema roles.

    Missing, malformed-identity, and hash-integrity errors from ``read_verified``
    are authority failures and propagate unchanged. Verified bytes that are not
    canonical objects, or canonical objects outside the requested schemas, are
    unrelated inputs and are skipped only after their one verified read.
    """

    if type(identities) is not tuple:
        raise TypeError("evidence input identities must be a tuple")
    if len(identities) != len(set(identities)):
        raise ValueError("evidence input identities must be unique")
    if type(required_schemas) is not tuple or not required_schemas:
        raise TypeError("required evidence schemas must be a non-empty tuple")
    schemas = tuple(
        _ascii_schema("required evidence schema", schema)
        for schema in required_schemas
    )
    if len(schemas) != len(set(schemas)):
        raise ValueError("required evidence schemas must be unique")

    matches: dict[str, list[CanonicalEvidenceInput]] = {
        schema: [] for schema in schemas
    }
    for identity in identities:
        content = store.read_verified(identity)
        try:
            value = parse_canonical(content)
        except CanonicalJSONError:
            continue
        if type(value) is not dict:
            continue
        schema = value.get("schema")
        if type(schema) is not str or schema not in matches:
            continue
        matches[schema].append(
            CanonicalEvidenceInput(
                artifact_sha256=identity,
                schema=schema,
                value=value,
            )
        )

    artifacts: list[CanonicalEvidenceInput] = []
    for schema in schemas:
        schema_matches = matches[schema]
        if len(schema_matches) != 1:
            raise ValueError(
                "evidence inputs require exactly one artifact for schema "
                f"{schema}: observed {len(schema_matches)}"
            )
        artifacts.append(schema_matches[0])
    return ExactEvidenceInputs(
        declared_identities=identities,
        artifacts=tuple(artifacts),
    )


def read_bound_evidence_inputs(
    store: VerifiedEvidenceReader,
    identities: tuple[str, ...],
    *,
    expected_bindings: tuple[tuple[str, str], ...],
) -> BoundEvidenceInputs:
    """Read an exact identity-to-schema evidence inventory once.

    A Job input inventory can also contain semantic digests that are not
    EvidenceStore objects.  The caller therefore passes the already-separated
    direct evidence identities.  Their inventory must exactly equal the
    expected bindings; multiple artifacts may intentionally share one schema.
    """

    if type(identities) is not tuple:
        raise TypeError("bound evidence input identities must be a tuple")
    declared = tuple(
        _sha256_digest("bound evidence input identity", identity)
        for identity in identities
    )
    if len(declared) != len(set(declared)):
        raise ValueError("bound evidence input identities must be unique")
    if type(expected_bindings) is not tuple or not expected_bindings:
        raise TypeError("expected evidence bindings must be a non-empty tuple")

    schemas_by_identity: dict[str, str] = {}
    for item in expected_bindings:
        if type(item) is not tuple or len(item) != 2:
            raise TypeError("expected evidence binding must be an identity pair")
        identity = _sha256_digest("expected evidence identity", item[0])
        schema = _ascii_schema("expected evidence schema", item[1])
        if identity in schemas_by_identity:
            raise ValueError("expected evidence identities must be unique")
        schemas_by_identity[identity] = schema

    if set(declared) != set(schemas_by_identity):
        raise ValueError(
            "declared evidence identities differ from expected bindings"
        )

    artifacts: list[CanonicalEvidenceInput] = []
    for identity in declared:
        content = store.read_verified(identity)
        try:
            value = parse_canonical(content)
        except CanonicalJSONError as exc:
            raise ValueError(
                "bound evidence input is not canonical JSON"
            ) from exc
        if type(value) is not dict:
            raise ValueError("bound evidence input is not a canonical object")
        expected_schema = schemas_by_identity[identity]
        if value.get("schema") != expected_schema:
            raise ValueError("bound evidence input schema differs from binding")
        artifacts.append(
            CanonicalEvidenceInput(
                artifact_sha256=identity,
                schema=expected_schema,
                value=value,
            )
        )
    return BoundEvidenceInputs(
        declared_identities=declared,
        artifacts=tuple(artifacts),
    )


def read_surface_manifest_evidence_inputs(
    store: VerifiedEvidenceReader,
    identities: tuple[str, ...],
    *,
    surface_schema: str,
    manifest_schema: str,
    expected_surface_implementation_sha256: str,
    manifest_surface_hash_field: str = "surface_artifact_hash",
) -> SurfaceManifestEvidenceInputs:
    """Verify surface content and its expected output implementation.

    This manifest check is not authority for an exact prior-Job producer.
    """

    surface_name = _ascii_schema("surface schema", surface_schema)
    manifest_name = _ascii_schema("surface manifest schema", manifest_schema)
    binding_field = _ascii_schema(
        "manifest surface hash field", manifest_surface_hash_field
    )
    expected_implementation = _sha256_digest(
        "expected surface implementation",
        expected_surface_implementation_sha256,
    )
    inputs = read_exact_evidence_inputs(
        store,
        identities,
        required_schemas=(surface_name, manifest_name),
    )
    surface = inputs.require(surface_name)
    manifest = inputs.require(manifest_name)
    if manifest.value.get(binding_field) != surface.artifact_sha256:
        raise ValueError("surface manifest is bound to another artifact")
    manifest_implementation = _sha256_digest(
        "surface manifest implementation",
        manifest.value.get("surface_implementation_sha256"),
    )
    if manifest_implementation != expected_implementation:
        raise ValueError("surface manifest implementation differs from expectation")
    return SurfaceManifestEvidenceInputs(surface=surface, manifest=manifest)


__all__ = [
    "BoundEvidenceInputs",
    "CanonicalEvidenceInput",
    "ExactEvidenceInputs",
    "SurfaceManifestEvidenceInputs",
    "VerifiedEvidenceReader",
    "read_bound_evidence_inputs",
    "read_exact_evidence_inputs",
    "read_surface_manifest_evidence_inputs",
]
