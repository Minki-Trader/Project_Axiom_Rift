from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import unittest

import yaml

from axiom_rift.operations.writer import (
    _TYPED_STARTED_BATCH_EXIT_ACTIVATION_OPERATION_ID,
)
from scripts.apply_typed_started_batch_exit_v1 import (
    AUTHORITY_OPERATION_ID,
    EXPECTED_SUCCESSOR_SHA256,
    desired_replacements,
    plan_activation,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


class TypedStartedBatchExitActivationTests(unittest.TestCase):
    def test_plan_materializes_exact_contract_without_writing(self) -> None:
        before = {
            relative: (REPO_ROOT / relative).read_bytes()
            for relative in EXPECTED_SUCCESSOR_SHA256
        }
        replacements, mode = desired_replacements(REPO_ROOT)
        self.assertIn(mode, {"activate", "already_materialized"})
        self.assertEqual(
            {
                relative: sha256(content).hexdigest()
                for relative, content in replacements.items()
            },
            EXPECTED_SUCCESSOR_SHA256,
        )
        science = yaml.safe_load(
            replacements["contracts/science.yaml"].decode("ascii")
        )
        operations = yaml.safe_load(
            replacements["contracts/operations.yaml"].decode("ascii")
        )
        representative = science["study_kpi_projection"][
            "representative_executable"
        ]
        self.assertTrue(
            representative[
                "started_nonbudget_exit_requires_exact_stop_completion"
            ]
        )
        self.assertFalse(
            representative["continue_batch_is_started_batch_close_authority"]
        )
        unavailable = representative["no_final_validator_completion"]
        self.assertEqual(
            unavailable["started_batch_outcomes"],
            {
                "budget_exhausted": (
                    "exact_frozen_compute_wall_or_trial_bound"
                )
            },
        )
        legacy = unavailable[
            "legacy_started_batch_outcomes_before_typed_exit_activation"
        ]
        self.assertTrue(legacy["read_only_projection_compatibility"])
        exit_contract = operations["repair"]["started_batch_exit"]
        self.assertEqual(
            exit_contract["no_final_completion_outcomes"],
            ["budget_exhausted"],
        )
        self.assertTrue(
            exit_contract[
                "engineering_not_evaluable_or_early_stop_requires_stop_batch"
            ]
        )
        self.assertFalse(
            exit_contract["continue_batch_can_dispose_started_batch"]
        )
        self.assertEqual(
            {
                relative: (REPO_ROOT / relative).read_bytes()
                for relative in EXPECTED_SUCCESSOR_SHA256
            },
            before,
        )

    def test_activation_plan_binds_writer_boundary_and_audit(self) -> None:
        self.assertEqual(
            AUTHORITY_OPERATION_ID,
            _TYPED_STARTED_BATCH_EXIT_ACTIVATION_OPERATION_ID,
        )
        plan = plan_activation(REPO_ROOT)
        self.assertEqual(
            plan["schema"],
            "typed_started_batch_exit_activation_plan.v1",
        )
        self.assertEqual(plan["authority_operation_id"], AUTHORITY_OPERATION_ID)
        self.assertEqual(
            plan["replacement_sha256"],
            EXPECTED_SUCCESSOR_SHA256,
        )


if __name__ == "__main__":
    unittest.main()

