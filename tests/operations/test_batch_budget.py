from __future__ import annotations

import unittest

from axiom_rift.operations.batch_budget import (
    BATCH_BUDGET_RESERVATION_REPAIR_SCHEMA,
    batch_budget_reservation_repair_manifest,
    registered_batch_budget_for_output_classes,
)


class BatchBudgetRepairTests(unittest.TestCase):
    def test_repair_releases_only_completed_reservation_capacity(self) -> None:
        manifest = batch_budget_reservation_repair_manifest(
            batch_id="batch:" + "1" * 64,
            frozen_budget_ceiling={
                "compute_seconds": 14_400,
                "wall_seconds": 21_600,
            },
            declared_job_budgets={
                "job:" + "2" * 64: {
                    "compute_seconds": 3_600,
                    "wall_seconds": 5_400,
                },
                "job:" + "3" * 64: {
                    "compute_seconds": 3_600,
                    "wall_seconds": 5_400,
                },
            },
            corrected_job_budgets={
                "job:" + "2" * 64: {
                    "compute_seconds": 3_600,
                    "wall_seconds": 5_400,
                },
                "job:" + "3" * 64: {
                    "compute_seconds": 900,
                    "wall_seconds": 1_440,
                },
            },
            job_implementation_identities={
                "job:" + "2" * 64: "4" * 64,
                "job:" + "3" * 64: "4" * 64,
            },
            policy_id="fixed_hold_replay.shared_family_cache.v2",
            reason="release an oversized cache-consumer reservation",
        )
        self.assertEqual(
            manifest["schema"],
            BATCH_BUDGET_RESERVATION_REPAIR_SCHEMA,
        )
        self.assertEqual(
            manifest["prior_reserved_totals"],
            {"compute_seconds": 7_200, "wall_seconds": 10_800},
        )
        self.assertEqual(
            manifest["corrected_reserved_totals"],
            {"compute_seconds": 4_500, "wall_seconds": 6_840},
        )
        self.assertEqual(manifest["scientific_trial_delta"], 0)

    def test_repair_cannot_increase_or_erase_a_reservation(self) -> None:
        common = {
            "batch_id": "batch:" + "1" * 64,
            "frozen_budget_ceiling": {
                "compute_seconds": 100,
                "wall_seconds": 100,
            },
            "declared_job_budgets": {
                "job:" + "2" * 64: {
                    "compute_seconds": 30,
                    "wall_seconds": 30,
                }
            },
            "job_implementation_identities": {
                "job:" + "2" * 64: "4" * 64
            },
            "policy_id": "fixture.repair.v1",
            "reason": "exercise reduction-only budget repair",
        }
        with self.assertRaisesRegex(ValueError, "cannot increase"):
            batch_budget_reservation_repair_manifest(
                **common,
                corrected_job_budgets={
                    "job:" + "2" * 64: {
                        "compute_seconds": 31,
                        "wall_seconds": 30,
                    }
                },
            )
        with self.assertRaisesRegex(ValueError, "positive"):
            batch_budget_reservation_repair_manifest(
                **common,
                corrected_job_budgets={
                    "job:" + "2" * 64: {
                        "compute_seconds": 0,
                        "wall_seconds": 30,
                    }
                },
            )

    def test_production_policy_is_closed_and_role_sensitive(self) -> None:
        self.assertEqual(
            registered_batch_budget_for_output_classes(
                policy_id="fixed_hold_replay.shared_family_cache.v2",
                output_classes={"family.json": "reproducible_cache"},
            ),
            {"compute_seconds": 3_600, "wall_seconds": 5_400},
        )
        self.assertEqual(
            registered_batch_budget_for_output_classes(
                policy_id="fixed_hold_replay.shared_family_cache.v2",
                output_classes={"result.json": "durable_evidence"},
            ),
            {"compute_seconds": 900, "wall_seconds": 1_440},
        )
        with self.assertRaisesRegex(ValueError, "not registered"):
            registered_batch_budget_for_output_classes(
                policy_id="arbitrary.discount.v1",
                output_classes={"result.json": "durable_evidence"},
            )


if __name__ == "__main__":
    unittest.main()
