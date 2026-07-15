from __future__ import annotations

import unittest

from scripts.apply_project_goal_audit_v1 import CORRECTION_OPERATION_PREFIX
from scripts.run_project_goal_audit_v1_forest_study import (
    ALL_STEPS,
    DIAGNOSE_STEPS,
    OPERATION_PREFIX,
    STUDY_CLOSE_STEPS,
)


class ProjectGoalAuditForestStudyTests(unittest.TestCase):
    def test_operation_plan_has_one_disjoint_strict_stage_split(self) -> None:
        operation_ids = tuple(step.operation_id for step in ALL_STEPS)
        self.assertEqual(len(STUDY_CLOSE_STEPS), 16)
        self.assertEqual(len(DIAGNOSE_STEPS), 4)
        self.assertEqual(len(operation_ids), len(set(operation_ids)))
        self.assertTrue(
            all(value.startswith(OPERATION_PREFIX) for value in operation_ids)
        )
        self.assertFalse(OPERATION_PREFIX.startswith(CORRECTION_OPERATION_PREFIX))
        self.assertEqual(STUDY_CLOSE_STEPS[-1].event_kind, "study_closed")
        self.assertEqual(
            DIAGNOSE_STEPS[0].event_kind,
            "study_diagnosis_recorded",
        )


if __name__ == "__main__":
    unittest.main()
