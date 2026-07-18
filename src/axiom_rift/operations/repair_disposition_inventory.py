"""Validator-derived Repair inventory facts and terminal decision rules.

This module contains no evidence I/O and grants no Writer authority.  It
normalizes facts returned by a registered domain validator, binds every
accepted attempt to its exact candidate axis, and derives a terminal outcome
without accepting caller-authored axis states or value estimates.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest


class RepairDispositionInventoryError(ValueError):
    """Registered Repair inventory facts are incomplete or inconsistent."""


REPAIR_INVENTORY_FACTS_SCHEMA = "engineering_repair_inventory_facts.v1"

_DIMENSIONS = frozenset(
    {"cause", "information", "input", "implementation", "scientific_semantics"}
)
_STATES = frozenset(
    {"attempt_failed", "infeasible", "invalidated", "remaining", "semantic_conflict"}
)
_AXIS_FIELDS = {
    "accepted_attempt_record_ids",
    "axis_id",
    "changed_dimension",
    "state",
    "support_evidence_hashes",
    "value_assessment",
}
_VALUE_FIELDS = {
    "as_of_basis_hash",
    "benefit_units",
    "cost_units",
    "estimate_receipt_hashes",
    "information_set_hash",
    "success_probability_ppm",
    "unit",
    "value_model_id",
}


def _document(value: object, *, label: str) -> dict[str, Any]:
    try:
        parsed = parse_canonical(canonical_bytes(value))
    except (TypeError, ValueError) as exc:
        raise RepairDispositionInventoryError(f"{label} is not canonical") from exc
    if not isinstance(parsed, dict):
        raise RepairDispositionInventoryError(f"{label} must be an object")
    return parsed


def _ascii(label: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise RepairDispositionInventoryError(f"{label} must be non-empty ASCII")
    return value


def _token(label: str, value: object) -> str:
    text = _ascii(label, value)
    if any(not (character.isalnum() or character in "-_.:") for character in text):
        raise RepairDispositionInventoryError(
            f"{label} must contain only ASCII token characters"
        )
    return text


def _digest(label: str, value: object) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise RepairDispositionInventoryError(
            f"{label} must be a lowercase SHA-256 digest"
        )
    return value


def _digests(label: str, value: object, *, allow_empty: bool) -> tuple[str, ...]:
    if (
        not isinstance(value, (list, tuple))
        or (not allow_empty and not value)
        or list(value) != sorted(set(value))
    ):
        raise RepairDispositionInventoryError(
            f"{label} must be a sorted unique digest list"
        )
    return tuple(_digest(label, item) for item in value)


def _nonnegative_integer(label: str, value: object) -> int:
    if type(value) is not int or value < 0:
        raise RepairDispositionInventoryError(
            f"{label} must be a non-negative integer"
        )
    return value


def repair_inventory_information_set_hash(
    *,
    cause_hash: str,
    current_basis_hash: str,
    accepted_attempts: Sequence[Mapping[str, Any]],
    validation_observations: Sequence[Mapping[str, Any]],
    validation_observation_head: Mapping[str, Any] | None,
) -> str:
    """Identify the exact information available to a Repair portfolio review."""

    cause = _digest("Repair inventory cause", cause_hash)
    basis = _digest("Repair inventory basis", current_basis_hash)
    try:
        attempts = parse_canonical(canonical_bytes(list(accepted_attempts)))
        observations = parse_canonical(canonical_bytes(list(validation_observations)))
        head = (
            None
            if validation_observation_head is None
            else parse_canonical(canonical_bytes(dict(validation_observation_head)))
        )
    except (TypeError, ValueError) as exc:
        raise RepairDispositionInventoryError(
            "Repair inventory information set is not canonical"
        ) from exc
    return canonical_digest(
        domain="engineering-repair-inventory-information-set",
        payload={
            "accepted_attempts": attempts,
            "cause_hash": cause,
            "current_basis_hash": basis,
            "validation_observation_head": head,
            "validation_observations": observations,
        },
    )


def normalize_repair_inventory_facts(
    value: object,
    *,
    accepted_attempts: Sequence[Mapping[str, Any]],
    current_basis_hash: str,
    information_set_hash: str,
    opened_result_artifact_hashes: Sequence[str],
) -> dict[str, Any]:
    """Bind registered inventory facts to exact attempts and opened evidence."""

    document = _document(value, label="engineering Repair inventory facts")
    if set(document) != {
        "axes",
        "coverage_complete",
        "no_identity_preserving_repair_route_remaining",
        "schema",
    } or document.get("schema") != REPAIR_INVENTORY_FACTS_SCHEMA:
        raise RepairDispositionInventoryError(
            "engineering Repair inventory facts schema is invalid"
        )
    if type(document.get("coverage_complete")) is not bool or type(
        document.get("no_identity_preserving_repair_route_remaining")
    ) is not bool:
        raise RepairDispositionInventoryError(
            "engineering Repair inventory completeness facts are invalid"
        )
    coverage_complete = bool(document["coverage_complete"])
    no_route_remaining = bool(
        document["no_identity_preserving_repair_route_remaining"]
    )
    if no_route_remaining and not coverage_complete:
        raise RepairDispositionInventoryError(
            "incomplete Repair inventory cannot prove route exhaustion"
        )

    expected_attempts: dict[str, tuple[str, str]] = {}
    for attempt in accepted_attempts:
        if not isinstance(attempt, Mapping):
            raise RepairDispositionInventoryError(
                "accepted Repair attempt inventory is malformed"
            )
        record_id = _digest(
            "accepted Repair attempt record",
            attempt.get("repair_attempt_record_id"),
        )
        axis_id = _token("accepted Repair attempt axis", attempt.get("repair_axis_id"))
        dimension = attempt.get("changed_dimension")
        if dimension not in _DIMENSIONS or record_id in expected_attempts:
            raise RepairDispositionInventoryError(
                "accepted Repair attempt axis binding is invalid"
            )
        expected_attempts[record_id] = (axis_id, str(dimension))

    opened_hashes = set(
        _digests(
            "Repair inventory opened result artifact",
            opened_result_artifact_hashes,
            allow_empty=False,
        )
    )
    current_basis = _digest("Repair inventory current basis", current_basis_hash)
    information_set = _digest(
        "Repair inventory information set", information_set_hash
    )
    axes_value = document.get("axes")
    if not isinstance(axes_value, list) or not axes_value:
        raise RepairDispositionInventoryError(
            "engineering Repair inventory requires at least one axis"
        )
    axes: list[dict[str, Any]] = []
    seen_axis_ids: set[str] = set()
    assigned_attempts: set[str] = set()
    for item in axes_value:
        if not isinstance(item, Mapping) or set(item) != _AXIS_FIELDS:
            raise RepairDispositionInventoryError(
                "engineering Repair inventory axis schema is invalid"
            )
        axis_id = _token("engineering Repair inventory axis", item.get("axis_id"))
        dimension = item.get("changed_dimension")
        state = item.get("state")
        if (
            axis_id in seen_axis_ids
            or dimension not in _DIMENSIONS
            or state not in _STATES
        ):
            raise RepairDispositionInventoryError(
                "engineering Repair inventory axis identity is invalid"
            )
        seen_axis_ids.add(axis_id)
        attempt_ids = _digests(
            "engineering Repair inventory accepted attempt",
            item.get("accepted_attempt_record_ids"),
            allow_empty=True,
        )
        for record_id in attempt_ids:
            expected = expected_attempts.get(record_id)
            if (
                expected != (axis_id, str(dimension))
                or record_id in assigned_attempts
            ):
                raise RepairDispositionInventoryError(
                    "accepted Repair attempt does not match its stored candidate axis"
                )
            assigned_attempts.add(record_id)
        if state == "attempt_failed" and not attempt_ids:
            raise RepairDispositionInventoryError(
                "failed Repair inventory axis lacks an accepted attempt"
            )
        support = _digests(
            "engineering Repair inventory support",
            item.get("support_evidence_hashes"),
            allow_empty=False,
        )
        if not set(support).issubset(opened_hashes):
            raise RepairDispositionInventoryError(
                "Repair inventory support was not opened by its validator"
            )
        value = item.get("value_assessment")
        normalized_value: dict[str, Any] | None = None
        if state == "remaining":
            if not isinstance(value, Mapping) or set(value) != _VALUE_FIELDS:
                raise RepairDispositionInventoryError(
                    "remaining Repair axis requires one validated value assessment"
                )
            probability = _nonnegative_integer(
                "Repair success probability", value.get("success_probability_ppm")
            )
            if probability > 1_000_000:
                raise RepairDispositionInventoryError(
                    "Repair success probability exceeds one"
                )
            estimate_receipts = _digests(
                "Repair value estimate receipt",
                value.get("estimate_receipt_hashes"),
                allow_empty=False,
            )
            if not set(estimate_receipts).issubset(opened_hashes):
                raise RepairDispositionInventoryError(
                    "Repair value estimates were not opened by their validator"
                )
            if (
                _digest("Repair value basis", value.get("as_of_basis_hash"))
                != current_basis
                or _digest(
                    "Repair value information set", value.get("information_set_hash")
                )
                != information_set
            ):
                raise RepairDispositionInventoryError(
                    "Repair value assessment names a stale information state"
                )
            normalized_value = {
                "as_of_basis_hash": current_basis,
                "benefit_units": _nonnegative_integer(
                    "Repair value benefit", value.get("benefit_units")
                ),
                "cost_units": _nonnegative_integer(
                    "Repair value cost", value.get("cost_units")
                ),
                "estimate_receipt_hashes": list(estimate_receipts),
                "information_set_hash": information_set,
                "success_probability_ppm": probability,
                "unit": _token("Repair value unit", value.get("unit")),
                "value_model_id": _token(
                    "Repair value model", value.get("value_model_id")
                ),
            }
        elif value is not None:
            raise RepairDispositionInventoryError(
                "terminal Repair axis cannot carry a prospective value estimate"
            )
        axes.append(
            {
                "accepted_attempt_record_ids": list(attempt_ids),
                "axis_id": axis_id,
                "changed_dimension": str(dimension),
                "state": str(state),
                "support_evidence_hashes": list(support),
                "value_assessment": normalized_value,
            }
        )
    if axes != sorted(axes, key=lambda item: item["axis_id"]):
        raise RepairDispositionInventoryError(
            "engineering Repair inventory axes must be sorted"
        )
    if assigned_attempts != set(expected_attempts):
        raise RepairDispositionInventoryError(
            "engineering Repair inventory omits an accepted attempt"
        )
    return {
        "axes": axes,
        "coverage_complete": coverage_complete,
        "no_identity_preserving_repair_route_remaining": no_route_remaining,
        "schema": REPAIR_INVENTORY_FACTS_SCHEMA,
    }


def derive_repair_disposition_from_inventory(
    inventory: Mapping[str, Any],
    *,
    observation_count: int,
    scientific_semantics_change_proven: bool,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Derive a terminal outcome only from registered complete inventory facts."""

    if type(observation_count) is not int or observation_count < 0 or type(
        scientific_semantics_change_proven
    ) is not bool:
        raise RepairDispositionInventoryError(
            "engineering Repair disposition inputs are invalid"
        )
    axes = inventory.get("axes")
    if (
        not isinstance(axes, list)
        or not axes
        or inventory.get("coverage_complete") is not True
    ):
        raise RepairDispositionInventoryError(
            "terminal Repair decision requires registered complete inventory"
        )
    no_route_remaining = inventory.get(
        "no_identity_preserving_repair_route_remaining"
    )
    if type(no_route_remaining) is not bool:
        raise RepairDispositionInventoryError(
            "Repair route-exhaustion fact is absent"
        )
    remaining = [item for item in axes if item.get("state") == "remaining"]
    semantic = [item for item in axes if item.get("state") == "semantic_conflict"]
    infeasible = [item for item in axes if item.get("state") == "infeasible"]
    expected_value_numerator = 0
    for item in remaining:
        value = item.get("value_assessment")
        if not isinstance(value, Mapping):
            raise RepairDispositionInventoryError(
                "remaining Repair axis lacks validated value facts"
            )
        expected_value_numerator += (
            int(value["success_probability_ppm"]) * int(value["benefit_units"])
            - 1_000_000 * int(value["cost_units"])
        )
    if semantic:
        if remaining:
            raise RepairDispositionInventoryError(
                "scientific change cannot bypass a remaining engineering axis"
            )
        if not scientific_semantics_change_proven or not no_route_remaining:
            raise RepairDispositionInventoryError(
                "scientific exit requires both an actual semantic change and "
                "registered exhaustion of identity-preserving routes"
            )
        disposition = "requires_scientific_change"
        basis = {
            "expected_value": "not_applicable",
            "remaining_changed_causes": [],
            "repairable_without_scientific_change": False,
            "scientific_semantics_change_required": True,
        }
    elif remaining:
        if expected_value_numerator > 0:
            raise RepairDispositionInventoryError(
                "positive-value engineering axes must remain active"
            )
        disposition = "repair_nonpositive_expected_value"
        basis = {
            "expected_value": "nonpositive",
            "remaining_changed_causes": [item["axis_id"] for item in remaining],
            "repairable_without_scientific_change": True,
            "scientific_semantics_change_required": False,
        }
    elif infeasible:
        if not no_route_remaining:
            raise RepairDispositionInventoryError(
                "Repair infeasibility requires registered route exhaustion"
            )
        disposition = "repair_infeasible"
        basis = {
            "expected_value": "not_applicable",
            "remaining_changed_causes": [],
            "repairable_without_scientific_change": False,
            "scientific_semantics_change_required": False,
        }
    else:
        if not no_route_remaining:
            raise RepairDispositionInventoryError(
                "changed-cause exhaustion requires registered complete coverage"
            )
        disposition = "repair_exhausted_changed_causes"
        basis = {
            "expected_value": "not_applicable",
            "remaining_changed_causes": [],
            "repairable_without_scientific_change": False,
            "scientific_semantics_change_required": False,
        }
    facts = {
        "disposition": disposition,
        "disposition_verified": True,
        "inventory_axis_count": len(axes),
        "no_identity_preserving_repair_route_remaining": no_route_remaining,
        "observation_count": observation_count,
        "scientific_semantics_change_proven": scientific_semantics_change_proven,
        **basis,
    }
    return disposition, basis, facts


__all__ = [
    "REPAIR_INVENTORY_FACTS_SCHEMA",
    "RepairDispositionInventoryError",
    "derive_repair_disposition_from_inventory",
    "normalize_repair_inventory_facts",
    "repair_inventory_information_set_hash",
]
