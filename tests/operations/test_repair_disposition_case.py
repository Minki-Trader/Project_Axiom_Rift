from __future__ import annotations

from copy import deepcopy

import pytest

from axiom_rift.operations.repair_disposition_case import (
    REPAIR_DISPOSITION_CASE_SCHEMA,
    RepairDispositionCaseError,
    derive_repair_disposition,
    normalize_repair_disposition_case,
)


FACTS = "1" * 64
INVENTORY_RECEIPT = "2" * 64
SEMANTIC_RECEIPT = "3" * 64


def _case(*, semantic: bool = False) -> dict[str, object]:
    return {
        "inventory_facts_artifact_hash": FACTS,
        "inventory_validation_receipt_hash": INVENTORY_RECEIPT,
        "schema": REPAIR_DISPOSITION_CASE_SCHEMA,
        "semantic_change_receipt_hash": (
            SEMANTIC_RECEIPT if semantic else None
        ),
    }


def test_case_contains_only_routes_to_independent_authority() -> None:
    assert normalize_repair_disposition_case(_case()) == _case()
    assert normalize_repair_disposition_case(_case(semantic=True)) == _case(
        semantic=True
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("axes", []),
        ("disposition", "repair_infeasible"),
        ("expected_value", "nonpositive"),
        ("no_identity_preserving_repair_route_remaining", True),
    ],
)
def test_case_rejects_caller_authored_judgment(
    field: str,
    value: object,
) -> None:
    attacked = deepcopy(_case())
    attacked[field] = value
    with pytest.raises(RepairDispositionCaseError, match="schema is invalid"):
        normalize_repair_disposition_case(attacked)


def test_case_rejects_missing_or_malformed_authority_routes() -> None:
    missing = deepcopy(_case())
    missing.pop("inventory_validation_receipt_hash")
    with pytest.raises(RepairDispositionCaseError):
        normalize_repair_disposition_case(missing)

    malformed = deepcopy(_case())
    malformed["inventory_facts_artifact_hash"] = "caller-facts"
    with pytest.raises(RepairDispositionCaseError, match="SHA-256"):
        normalize_repair_disposition_case(malformed)


def test_derive_uses_registered_inventory_not_case_fields() -> None:
    inventory = {
        "axes": [
            {
                "accepted_attempt_record_ids": [],
                "axis_id": "repair-route-a",
                "changed_dimension": "implementation",
                "state": "infeasible",
                "support_evidence_hashes": ["4" * 64],
                "value_assessment": None,
            }
        ],
        "coverage_complete": True,
        "no_identity_preserving_repair_route_remaining": True,
        "schema": "engineering_repair_inventory_facts.v1",
    }
    disposition, basis, facts = derive_repair_disposition(
        inventory,
        observation_count=7,
        scientific_semantics_change_proven=False,
    )
    assert disposition == "repair_infeasible"
    assert basis["repairable_without_scientific_change"] is False
    assert facts["observation_count"] == 7
