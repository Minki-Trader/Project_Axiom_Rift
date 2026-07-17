from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "run_p0_stu0051_fixed_hold_reentry.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location(
        "run_p0_stu0051_fixed_hold_reentry_test",
        RUNNER,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("fixed-hold reentry handoff is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class P0Stu0051FixedHoldReentryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = _load_runner()

    def test_completed_runner_delegates_to_the_common_handoff(self) -> None:
        with patch.object(
            self.runner,
            "run_fixed_hold_replay_command",
            return_value={"mode": "completed_study_handoff"},
        ) as command:
            self.runner.main([])

        self.assertEqual(command.call_args.kwargs["study_id"], "STU-0114")
        self.assertIs(
            command.call_args.kwargs["design_builder"],
            self.runner._closed_design,
        )

    def test_closed_design_fails_without_reconstructing_old_repair_state(
        self,
    ) -> None:
        with self.assertRaisesRegex(RuntimeError, "no prospective design"):
            self.runner._closed_design(object())


if __name__ == "__main__":
    unittest.main()
