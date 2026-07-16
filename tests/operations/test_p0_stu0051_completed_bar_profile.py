from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import axiom_rift.operations.volatility_duration_replay_profile as profile_module
from axiom_rift.operations.fixed_hold_replay_workflow import (
    ReplayAxisAdmission,
    ReplayInitiativeLifecycle,
)
from axiom_rift.research.semantic_question import SemanticQuestionRelation


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "run_p0_stu0051_completed_bar_replay.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location(
        "run_p0_stu0051_completed_bar_replay_test",
        RUNNER,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("P0 STU-0051 runner is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class P0Stu0051CompletedBarProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = _load_runner()

    def test_profile_binds_current_borrowed_authority_and_lineage(self) -> None:
        spec = self.runner.mission_spec()
        lineage = self.runner.semantic_question_lineage()

        self.assertIs(
            spec.initiative_lifecycle,
            ReplayInitiativeLifecycle.BORROW_ACTIVE_INITIATIVE,
        )
        self.assertEqual((spec.mission_id, spec.initiative_id), ("MIS-0006", "INI-0025"))
        self.assertEqual((spec.study_id, spec.batch_display_id), ("STU-0113", "BAT-0113"))
        self.assertIs(spec.axis_admission, ReplayAxisAdmission.REVISE_PROTOCOL)
        self.assertEqual(spec.boundary.sequence, 5394)
        self.assertEqual(
            spec.boundary.event_id,
            "cf68a2c0a29b78ea6f52a8fce3b859b1dd5068347b1701b7ee0e981cd92c9bbf",
        )
        self.assertEqual(
            spec.operation_prefix,
            "p0-stu0051-completed-bar-replay-v2-",
        )
        self.assertFalse(hasattr(self.runner, "HISTORICAL_CONTEXT_COUNT"))
        self.assertEqual(
            lineage.relation,
            SemanticQuestionRelation.CONTINUATION,
        )
        self.assertEqual(lineage.predecessor_study_id, "STU-0108")
        self.assertEqual(lineage.successor_study_id, spec.study_id)
        self.assertEqual(lineage.predecessor_core_id, lineage.successor_core_id)

    def test_production_builder_cannot_drop_authority_lineage_or_gate(self) -> None:
        design = SimpleNamespace(
            controlled_chassis=SimpleNamespace(
                architecture_family=self.runner.EXPECTED_ARCHITECTURE_FAMILY
            )
        )
        writer = Mock()
        with (
            patch.object(
                self.runner,
                "build_volatility_duration_replay_profile_design",
                return_value=design,
            ) as build,
            patch.object(
                self.runner,
                "require_borrowed_production_profile",
                return_value=design,
            ) as gate,
        ):
            self.assertIs(self.runner.build_design(writer), design)

        kwargs = build.call_args.kwargs
        self.assertIs(
            kwargs["spec"].initiative_lifecycle,
            ReplayInitiativeLifecycle.BORROW_ACTIVE_INITIATIVE,
        )
        self.assertEqual(
            kwargs["historical_family_authority_id"],
            self.runner.HISTORICAL_FAMILY_AUTHORITY_ID,
        )
        self.assertNotIn("historical_context_count", kwargs)
        self.assertEqual(
            kwargs["semantic_question_lineage"],
            self.runner.semantic_question_lineage(),
        )
        gate.assert_called_once_with(writer, design)

    def test_reconstruction_profile_has_no_new_executable_generator(self) -> None:
        source = Path(profile_module.__file__).read_text(encoding="ascii")
        self.assertIn("executable_from_identity_payload", source)
        self.assertIn(
            "project_historical_family_end_global_exposure_count",
            source,
        )
        self.assertNotIn(
            "from axiom_rift.research.volatility_duration_replay import",
            source,
        )
        self.assertNotIn("historical_context_count:", source)


if __name__ == "__main__":
    unittest.main()
