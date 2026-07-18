"""Neutral cause-inventory case behind a terminal engineering decision."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.operations.repair_disposition_inventory import (
    RepairDispositionInventoryError,
    derive_repair_disposition_from_inventory,
)


class RepairDispositionCaseError(ValueError):
    """A disposition case is partial, ambiguous, or outcome-authored."""


REPAIR_DISPOSITION_CASE_SCHEMA = "engineering_repair_disposition_case.v3"
SEMANTIC_CHANGE_CASE_SCHEMA = "engineering_semantic_change_case.v1"


def _document(value: bytes | Mapping[str, Any], *, label: str) -> dict[str, Any]:
    try:
        parsed = parse_canonical(value) if isinstance(value, bytes) else dict(value)
        canonical_bytes(parsed)
    except (TypeError, ValueError) as exc:
        raise RepairDispositionCaseError(f"{label} is not canonical") from exc
    if not isinstance(parsed, dict):
        raise RepairDispositionCaseError(f"{label} must be an object")
    return parsed


def _ascii(label: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise RepairDispositionCaseError(f"{label} must be non-empty ASCII")
    return value


def _digest(label: str, value: object) -> str:
    text = _ascii(label, value)
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise RepairDispositionCaseError(f"{label} must be a SHA-256 digest")
    return text


def _nullable_digest(label: str, value: object) -> str | None:
    return None if value is None else _digest(label, value)


def _digests(
    label: str,
    value: object,
    *,
    allow_empty: bool,
) -> tuple[str, ...]:
    if (
        not isinstance(value, (list, tuple))
        or (not allow_empty and not value)
    ):
        raise RepairDispositionCaseError(f"{label} must be a digest list")
    normalized = tuple(_digest(label, item) for item in value)
    if normalized != tuple(sorted(set(normalized))):
        raise RepairDispositionCaseError(
            f"{label} must be sorted and unique"
        )
    return normalized


def normalize_repair_disposition_case(
    value: bytes | Mapping[str, Any],
) -> dict[str, Any]:
    """Validate an outcome-free route to registered inventory authority."""

    document = _document(value, label="engineering Repair disposition case")
    if set(document) != {
        "inventory_facts_artifact_hash",
        "inventory_validation_receipt_hash",
        "schema",
        "semantic_change_receipt_hash",
    } or document.get("schema") != REPAIR_DISPOSITION_CASE_SCHEMA:
        raise RepairDispositionCaseError(
            "engineering Repair disposition case schema is invalid"
        )
    inventory_receipt = _digest(
        "engineering Repair inventory validation receipt",
        document.get("inventory_validation_receipt_hash"),
    )
    inventory_facts = _digest(
        "engineering Repair inventory facts artifact",
        document.get("inventory_facts_artifact_hash"),
    )
    semantic_receipt = _nullable_digest(
        "engineering semantic-change receipt",
        document.get("semantic_change_receipt_hash"),
    )
    return {
        "inventory_facts_artifact_hash": inventory_facts,
        "inventory_validation_receipt_hash": inventory_receipt,
        "schema": REPAIR_DISPOSITION_CASE_SCHEMA,
        "semantic_change_receipt_hash": semantic_receipt,
    }


def derive_repair_disposition(
    inventory: Mapping[str, Any],
    *,
    observation_count: int,
    scientific_semantics_change_proven: bool,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Compatibility wrapper around registered inventory decision rules."""

    try:
        return derive_repair_disposition_from_inventory(
            inventory,
            observation_count=observation_count,
            scientific_semantics_change_proven=(
                scientific_semantics_change_proven
            ),
        )
    except RepairDispositionInventoryError as exc:
        raise RepairDispositionCaseError(str(exc)) from exc


def normalize_semantic_change_case(
    value: bytes | Mapping[str, Any],
) -> dict[str, Any]:
    """Validate neutral changed/protected dimensions without an outcome bit."""

    document = _document(value, label="engineering semantic-change case")
    if set(document) != {
        "changed_dimensions",
        "correction_artifact_hashes",
        "protected_semantic_dimensions",
        "rationale_evidence_hashes",
        "schema",
    } or document.get("schema") != SEMANTIC_CHANGE_CASE_SCHEMA:
        raise RepairDispositionCaseError(
            "engineering semantic-change case schema is invalid"
        )
    changed = document.get("changed_dimensions")
    protected = document.get("protected_semantic_dimensions")
    if (
        not isinstance(changed, list)
        or not isinstance(protected, list)
        or not changed
        or not protected
        or changed != sorted(set(changed))
        or protected != sorted(set(protected))
    ):
        raise RepairDispositionCaseError(
            "engineering semantic-change dimensions must be sorted and unique"
        )
    normalized_changed = [
        _ascii("changed semantic dimension", item) for item in changed
    ]
    normalized_protected = [
        _ascii("protected semantic dimension", item) for item in protected
    ]
    return {
        "changed_dimensions": normalized_changed,
        "correction_artifact_hashes": list(
            _digests(
                "semantic-change correction artifact",
                document.get("correction_artifact_hashes"),
                allow_empty=False,
            )
        ),
        "protected_semantic_dimensions": normalized_protected,
        "rationale_evidence_hashes": list(
            _digests(
                "semantic-change rationale evidence",
                document.get("rationale_evidence_hashes"),
                allow_empty=False,
            )
        ),
        "schema": SEMANTIC_CHANGE_CASE_SCHEMA,
    }


def semantic_change_facts(
    case: Mapping[str, Any],
    *,
    current_basis_hash: str,
    accepted_attempt_head_record_id: str | None,
    repair_validation_observation_head: Mapping[str, Any] | None,
) -> dict[str, Any]:
    changed = case.get("changed_dimensions")
    protected = case.get("protected_semantic_dimensions")
    if not isinstance(changed, list) or not isinstance(protected, list):
        raise RepairDispositionCaseError(
            "engineering semantic-change dimensions are absent"
        )
    conflicts = sorted(set(changed).intersection(protected))
    if not conflicts:
        raise RepairDispositionCaseError(
            "correction preserves every protected scientific dimension"
        )
    return {
        "accepted_attempt_head_record_id": accepted_attempt_head_record_id,
        "changed_protected_dimensions": conflicts,
        "current_basis_hash": _digest(
            "semantic-change current basis", current_basis_hash
        ),
        "identity_preservation_possible": False,
        "repair_validation_observation_head": (
            None
            if repair_validation_observation_head is None
            else dict(repair_validation_observation_head)
        ),
        "semantic_change_necessary": True,
    }


__all__ = [
    "REPAIR_DISPOSITION_CASE_SCHEMA",
    "SEMANTIC_CHANGE_CASE_SCHEMA",
    "RepairDispositionCaseError",
    "derive_repair_disposition",
    "normalize_repair_disposition_case",
    "normalize_semantic_change_case",
    "semantic_change_facts",
]
