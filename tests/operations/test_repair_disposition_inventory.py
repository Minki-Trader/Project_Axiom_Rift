from __future__ import annotations

import unittest

from axiom_rift.operations.repair_disposition_inventory import (
    REPAIR_INVENTORY_FACTS_SCHEMA,
    RepairDispositionInventoryError,
    derive_repair_disposition_from_inventory,
    normalize_repair_inventory_facts,
)


def _digest(character: str) -> str:
    return character * 64


class RepairDispositionInventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.attempt_id = _digest("1")
        self.support = _digest("2")
        self.basis = _digest("3")
        self.information_set = _digest("4")
        self.attempts = (
            {
                "changed_dimension": "implementation",
                "repair_attempt_record_id": self.attempt_id,
                "repair_axis_id": "implementation-source-closure",
            },
        )

    def _facts(self, *, state: str = "attempt_failed") -> dict[str, object]:
        return {
            "axes": [
                {
                    "accepted_attempt_record_ids": [self.attempt_id],
                    "axis_id": "implementation-source-closure",
                    "changed_dimension": "implementation",
                    "state": state,
                    "support_evidence_hashes": [self.support],
                    "value_assessment": None,
                }
            ],
            "coverage_complete": True,
            "no_identity_preserving_repair_route_remaining": True,
            "schema": REPAIR_INVENTORY_FACTS_SCHEMA,
        }

    def _normalize(self, facts: dict[str, object]) -> dict[str, object]:
        return normalize_repair_inventory_facts(
            facts,
            accepted_attempts=self.attempts,
            current_basis_hash=self.basis,
            information_set_hash=self.information_set,
            opened_result_artifact_hashes=(self.support,),
        )

    def test_complete_registered_coverage_replaces_numeric_attempt_cap(self) -> None:
        inventory = self._normalize(self._facts())
        disposition, _basis, facts = derive_repair_disposition_from_inventory(
            inventory,
            observation_count=0,
            scientific_semantics_change_proven=False,
        )
        self.assertEqual(disposition, "repair_exhausted_changed_causes")
        self.assertEqual(facts["inventory_axis_count"], 1)

    def test_attempt_axis_must_match_stored_candidate(self) -> None:
        facts = self._facts()
        facts["axes"][0]["axis_id"] = "caller-invented-axis"
        with self.assertRaisesRegex(
            RepairDispositionInventoryError,
            "stored candidate axis",
        ):
            self._normalize(facts)

    def test_incomplete_inventory_cannot_end_repair(self) -> None:
        facts = self._facts()
        facts["coverage_complete"] = False
        facts["no_identity_preserving_repair_route_remaining"] = False
        inventory = self._normalize(facts)
        with self.assertRaisesRegex(
            RepairDispositionInventoryError,
            "registered complete inventory",
        ):
            derive_repair_disposition_from_inventory(
                inventory,
                observation_count=0,
                scientific_semantics_change_proven=False,
            )

    def test_remaining_axis_uses_current_validated_value_receipts(self) -> None:
        estimate = _digest("5")
        facts = self._facts(state="remaining")
        facts["no_identity_preserving_repair_route_remaining"] = False
        facts["axes"][0]["value_assessment"] = {
            "as_of_basis_hash": self.basis,
            "benefit_units": 2,
            "cost_units": 3,
            "estimate_receipt_hashes": [estimate],
            "information_set_hash": self.information_set,
            "success_probability_ppm": 500_000,
            "unit": "bounded-work-unit",
            "value_model_id": "quant-team-repair-value-v1",
        }
        inventory = normalize_repair_inventory_facts(
            facts,
            accepted_attempts=self.attempts,
            current_basis_hash=self.basis,
            information_set_hash=self.information_set,
            opened_result_artifact_hashes=(self.support, estimate),
        )
        disposition, basis, _facts = derive_repair_disposition_from_inventory(
            inventory,
            observation_count=1,
            scientific_semantics_change_proven=False,
        )
        self.assertEqual(disposition, "repair_nonpositive_expected_value")
        self.assertEqual(
            basis["remaining_changed_causes"],
            ["implementation-source-closure"],
        )

    def test_scientific_exit_needs_change_and_no_identity_preserving_route(self) -> None:
        inventory = self._normalize(self._facts(state="semantic_conflict"))
        with self.assertRaisesRegex(
            RepairDispositionInventoryError,
            "both an actual semantic change",
        ):
            derive_repair_disposition_from_inventory(
                inventory,
                observation_count=0,
                scientific_semantics_change_proven=False,
            )
        disposition, _basis, facts = derive_repair_disposition_from_inventory(
            inventory,
            observation_count=0,
            scientific_semantics_change_proven=True,
        )
        self.assertEqual(disposition, "requires_scientific_change")
        self.assertTrue(
            facts["no_identity_preserving_repair_route_remaining"]
        )


if __name__ == "__main__":
    unittest.main()
