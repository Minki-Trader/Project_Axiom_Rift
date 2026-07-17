from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "run_p0_stu0051_fixed_hold_reentry.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location(
        "run_p0_stu0051_fixed_hold_reentry_test",
        RUNNER,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("P0 STU-0051 fixed-hold runner is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class P0Stu0051FixedHoldReentryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = _load_runner()

    def test_engineering_reentry_uses_exact_semantic_record_references(self) -> None:
        lineage = self.runner.semantic_question_lineage()

        self.assertEqual(
            lineage.basis_record_ids,
            (
                "job-implementation-preflight:"
                + self.runner.REPLACED_PREFLIGHT_ID,
                "study-close:" + self.runner.PREDECESSOR_CLOSE_RECORD_ID,
                "study-diagnosis:" + self.runner.DIAGNOSIS_ID,
                "study-open:" + self.runner.PREDECESSOR_STUDY_ID,
            ),
        )


if __name__ == "__main__":
    unittest.main()
