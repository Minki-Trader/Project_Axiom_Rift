"""Derive exact source-dependent runtime lifecycle coverage.

The executable manifest, rather than a caller-authored summary, is the
authority for which source-dependent subjects must be exercised.  These
helpers deliberately return canonical plain data so StateWriter can bind the
same matrix at Job declaration, completion, and Release assembly.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest


class SourceLifecycleCoverageError(ValueError):
    """The frozen executable cannot yield an unambiguous coverage matrix."""


_SOURCE_PREFIX = "source:"
_COVERAGE_PREFIX = "source-lifecycle-coverage:"
_LIFECYCLE_PREFIX = "lifecycle-surface:"
_CASE_EXPECTATIONS = {
    "source_interruption": {
        "dependent_position_state": "held",
        "required_dependent_action": "preregistered_safe_exit",
    },
    "stale_or_missing_input": {
        "dependent_position_state": "flat",
        "required_dependent_action": "no_entry",
    },
}


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise SourceLifecycleCoverageError(f"{name} must be non-empty ASCII")
    return value


def _typed_digest(name: str, value: object, prefix: str) -> str:
    text = _ascii(name, value)
    digest = text.removeprefix(prefix)
    if (
        not text.startswith(prefix)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise SourceLifecycleCoverageError(f"{name} is invalid")
    return text


def _canonical_manifest(value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        detached = parse_canonical(canonical_bytes(dict(value)))
    except (TypeError, ValueError) as exc:
        raise SourceLifecycleCoverageError(
            "executable manifest is not canonical"
        ) from exc
    if not isinstance(detached, dict):
        raise SourceLifecycleCoverageError("executable manifest is invalid")
    return detached


def derive_source_lifecycle_coverage(
    executable_manifest: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    """Return the exact source x dependent-component x failure-case matrix."""

    manifest = _canonical_manifest(executable_manifest)
    required_fields = {
        "clock_contract",
        "component_identities",
        "component_manifests",
        "cost_contract",
        "data_contract",
        "engine_contract",
        "parameters",
        "schema",
        "source_contracts",
        "split_contract",
    }
    if set(manifest) != required_fields:
        raise SourceLifecycleCoverageError(
            "executable manifest schema is invalid"
        )
    component_ids = manifest["component_identities"]
    component_manifests = manifest["component_manifests"]
    source_ids = manifest["source_contracts"]
    if (
        not isinstance(component_ids, list)
        or not component_ids
        or len(component_ids) != len(set(component_ids))
        or not isinstance(component_manifests, list)
        or len(component_manifests) != len(component_ids)
        or not isinstance(source_ids, list)
        or source_ids != sorted(set(source_ids))
    ):
        raise SourceLifecycleCoverageError(
            "executable component or source inventory is ambiguous"
        )
    normalized_components: list[tuple[str, dict[str, Any]]] = []
    declared_sources: set[str] = set()
    for expected_id, component in zip(component_ids, component_manifests):
        component_id = _typed_digest(
            "component identity", expected_id, "component:"
        )
        if not isinstance(component, dict):
            raise SourceLifecycleCoverageError("component manifest is invalid")
        actual_id = "component:" + canonical_digest(
            domain="component", payload=component
        )
        if actual_id != component_id:
            raise SourceLifecycleCoverageError(
                "component identity differs from its manifest"
            )
        dependencies = component.get("semantic_dependencies")
        if (
            not isinstance(dependencies, list)
            or dependencies != sorted(set(dependencies))
            or any(type(item) is not str for item in dependencies)
        ):
            raise SourceLifecycleCoverageError(
                "component semantic dependencies are invalid"
            )
        declared_sources.update(
            item for item in dependencies if item.startswith(_SOURCE_PREFIX)
        )
        normalized_components.append((component_id, component))
    normalized_sources = {
        _typed_digest("source contract identity", source, _SOURCE_PREFIX)
        for source in source_ids
    }
    if declared_sources != normalized_sources:
        raise SourceLifecycleCoverageError(
            "source inventory differs from component dependencies"
        )
    if not normalized_sources:
        return ()

    lifecycle_payload = {
        "clock_contract": _ascii(
            "clock contract", manifest["clock_contract"]
        ),
        "component_identities": list(component_ids),
        "cost_contract": _ascii("cost contract", manifest["cost_contract"]),
        "engine_contract": _ascii(
            "engine contract", manifest["engine_contract"]
        ),
        "schema": "source_dependent_lifecycle_surface.v1",
    }
    lifecycle_surface_id = _LIFECYCLE_PREFIX + canonical_digest(
        domain="source-dependent-lifecycle-surface",
        payload=lifecycle_payload,
    )
    rows: list[dict[str, Any]] = []
    for source_id in sorted(normalized_sources):
        dependent_components = [
            component_id
            for component_id, component in normalized_components
            if source_id in component["semantic_dependencies"]
        ]
        if not dependent_components:
            raise SourceLifecycleCoverageError(
                "source contract has no dependent component"
            )
        for component_id in sorted(dependent_components):
            for materialization_case, expectation in sorted(
                _CASE_EXPECTATIONS.items()
            ):
                identity_payload = {
                    "dependent_component_id": component_id,
                    "dependent_position_state": expectation[
                        "dependent_position_state"
                    ],
                    "independent_control_outcome": "unchanged",
                    "lifecycle_surface_id": lifecycle_surface_id,
                    "materialization_case": materialization_case,
                    "required_dependent_action": expectation[
                        "required_dependent_action"
                    ],
                    "retain_baseline_pnl_for_missing_subject": False,
                    "schema": "source_lifecycle_coverage_row.v1",
                    "source_contract_id": source_id,
                    "unrelated_sleeve_outcome": "unchanged",
                }
                coverage_id = _COVERAGE_PREFIX + canonical_digest(
                    domain="source-lifecycle-coverage-row",
                    payload=identity_payload,
                )
                rows.append(
                    {"coverage_id": coverage_id, **identity_payload}
                )
    return tuple(sorted(rows, key=lambda row: row["coverage_id"]))


def require_source_lifecycle_coverage_ids(
    value: object,
    *,
    allowed_rows: Sequence[Mapping[str, Any]],
    planned_materialization_cases: Sequence[str],
) -> tuple[str, ...]:
    """Validate a Job's planned coverage as a canonical subset of the matrix."""

    if not isinstance(value, (list, tuple)) or any(
        type(item) is not str for item in value
    ):
        raise SourceLifecycleCoverageError(
            "planned source lifecycle coverage must be an identity list"
        )
    identities = tuple(value)
    if identities != tuple(sorted(set(identities))):
        raise SourceLifecycleCoverageError(
            "planned source lifecycle coverage must be sorted and unique"
        )
    allowed_by_id: dict[str, Mapping[str, Any]] = {}
    for row in allowed_rows:
        if not isinstance(row, Mapping):
            raise SourceLifecycleCoverageError(
                "derived source lifecycle coverage row is invalid"
            )
        coverage_id = _typed_digest(
            "source lifecycle coverage identity",
            row.get("coverage_id"),
            _COVERAGE_PREFIX,
        )
        if coverage_id in allowed_by_id:
            raise SourceLifecycleCoverageError(
                "derived source lifecycle coverage is duplicated"
            )
        allowed_by_id[coverage_id] = row
    if not allowed_by_id:
        if identities:
            raise SourceLifecycleCoverageError(
                "source-free candidate cannot claim lifecycle coverage"
            )
        return ()
    if not set(identities).issubset(allowed_by_id):
        raise SourceLifecycleCoverageError(
            "planned source lifecycle coverage exceeds the frozen candidate"
        )
    planned_cases = set(planned_materialization_cases)
    if any(
        allowed_by_id[identity].get("materialization_case") not in planned_cases
        for identity in identities
    ):
        raise SourceLifecycleCoverageError(
            "source lifecycle coverage exceeds the Job's materialization cases"
        )
    required_planned_cases = planned_cases.intersection(_CASE_EXPECTATIONS)
    represented_cases = {
        str(allowed_by_id[identity]["materialization_case"])
        for identity in identities
    }
    if required_planned_cases and represented_cases != required_planned_cases:
        raise SourceLifecycleCoverageError(
            "source lifecycle materialization cases lack planned coverage"
        )
    if not required_planned_cases and identities:
        raise SourceLifecycleCoverageError(
            "non-lifecycle materialization cannot claim lifecycle coverage"
        )
    return identities


__all__ = [
    "SourceLifecycleCoverageError",
    "derive_source_lifecycle_coverage",
    "require_source_lifecycle_coverage_ids",
]
