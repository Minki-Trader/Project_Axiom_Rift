from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

from axiom_rift.operations.fixed_hold_replay_workflow import (
    ReplayAxisAdmission,
    ReplayInitiativeLifecycle,
)
from axiom_rift.operations.job_implementation_authority import (
    hardcoded_control_ids,
)
from axiom_rift.research.drawdown_state_replay_job import RUNTIME_ADAPTER


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "run_p0_stu0048_drawdown_reentry.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location(
        "run_p0_stu0048_drawdown_reentry_test",
        RUNNER,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("P0 drawdown reentry runner is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class P0Stu0048DrawdownReentryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = _load_runner()

    def test_spec_revises_the_exact_p0_axis_without_owning_initiative(self) -> None:
        spec = self.runner.mission_spec()

        self.assertIs(spec.axis_admission, ReplayAxisAdmission.REVISE_PROTOCOL)
        self.assertIs(
            spec.initiative_lifecycle,
            ReplayInitiativeLifecycle.BORROW_ACTIVE_INITIATIVE,
        )
        self.assertEqual(spec.study_id, "STU-0115")
        self.assertEqual(spec.target_obligation_id, self.runner.TARGET_OBLIGATION_ID)
        self.assertEqual(spec.boundary.sequence, 5452)
        self.assertEqual(spec.boundary.event_id, self.runner.PREDECESSOR_EVENT_ID)

    def test_lineage_continues_the_exact_predecessor_question(self) -> None:
        lineage = self.runner.semantic_question_lineage()

        self.assertEqual(lineage.predecessor_study_id, "STU-0107")
        self.assertEqual(lineage.successor_study_id, "STU-0115")
        self.assertEqual(lineage.predecessor_core_id, lineage.successor_core_id)
        self.assertEqual(
            lineage.basis_record_ids,
            (
                "study-close:" + self.runner.PREDECESSOR_CLOSE_RECORD_ID,
                "study-open:STU-0107",
            ),
        )

    def test_prospective_job_closure_contains_no_static_control_identity(
        self,
    ) -> None:
        for path in RUNTIME_ADAPTER.dependency_paths:
            with self.subTest(path=path.name):
                self.assertEqual(hardcoded_control_ids(path.read_bytes()), ())

    def test_main_uses_common_cli_and_pins_the_new_study(self) -> None:
        with patch.object(
            self.runner,
            "run_fixed_hold_replay_command",
            return_value={"mode": "read_only_plan"},
        ) as command:
            self.runner.main([])

        self.assertEqual(command.call_args.kwargs["study_id"], "STU-0115")
        self.assertIs(command.call_args.kwargs["design_builder"], self.runner.build_design)


if __name__ == "__main__":
    unittest.main()
