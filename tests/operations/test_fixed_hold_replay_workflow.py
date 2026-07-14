from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from axiom_rift.operations.fixed_hold_replay_workflow import (
    DIAGNOSE_STAGE,
    STUDY_CLOSE_STAGE,
    FixedHoldReplayMissionSpec,
    ReplayAuthorityBoundary,
    operation_steps,
)


class FixedHoldReplayWorkflowTests(unittest.TestCase):
    def _spec(self) -> FixedHoldReplayMissionSpec:
        return FixedHoldReplayMissionSpec(
            mission_id="MIS-9001",
            initiative_id="INI-9001",
            study_id="STU-9001",
            batch_display_id="BAT-9001",
            axis_id="axis-fixture-replay",
            operation_prefix="fixture-fixed-hold-replay-",
            decision_prefix="DEC-FIXTURE-REPLAY",
            target_obligation_id=(
                "historical-replay-obligation:" + "1" * 64
            ),
            original_study_id="STU-8001",
            job_protocol="python.source.fixture.v1",
            callable_identity="fixture.fixed_hold.execute.v1",
            job_implementation_identity="2" * 64,
            permit_expiry_utc="2027-12-31T23:59:59Z",
            boundary=ReplayAuthorityBoundary(
                sequence=100,
                event_id="3" * 64,
            ),
            display_name="fixture exact replay family",
        )

    def _design(self):
        members = tuple(
            SimpleNamespace(ordinal=value, label=f"member-{value:02d}")
            for value in range(1, 5)
        )
        return SimpleNamespace(
            spec=self._spec(),
            members=members,
            target_member=members[-1],
            criterion_ids=("criterion-a",),
        )

    @patch(
        "axiom_rift.operations.fixed_hold_replay_workflow._member_completion",
        return_value=None,
    )
    def test_operation_plan_is_one_exact_two_stage_chain(self, _completion) -> None:
        steps = operation_steps(SimpleNamespace(), self._design())
        self.assertEqual(len(steps), 39)
        self.assertEqual(len({item.operation_id for item in steps}), 39)
        self.assertEqual(
            sum(item.stage == STUDY_CLOSE_STAGE for item in steps),
            34,
        )
        self.assertEqual(
            sum(item.stage == DIAGNOSE_STAGE for item in steps),
            5,
        )
        self.assertEqual(
            steps[-4].event_kind,
            "historical_replay_obligations_deferred",
        )

    def test_failed_member_adds_memory_without_changing_replay_coverage(self) -> None:
        design = self._design()
        failed = SimpleNamespace(
            payload={"scientific": {"verdict": "failed"}}
        )
        target = SimpleNamespace(
            payload={"scientific": {"verdict": "not_evaluable"}}
        )

        def completion(_writer, _design, member):
            if member.ordinal == 1:
                return failed
            if member.ordinal == 4:
                return target
            return None

        interpretation = SimpleNamespace(all_criteria_recomputed=True)
        with (
            patch(
                "axiom_rift.operations.fixed_hold_replay_workflow._member_completion",
                side_effect=completion,
            ),
            patch(
                "axiom_rift.operations.fixed_hold_replay_workflow."
                "interpret_fixed_hold_completion",
                return_value=interpretation,
            ),
        ):
            steps = operation_steps(SimpleNamespace(), design)
        self.assertEqual(len(steps), 40)
        self.assertIn(
            design.spec.operation_prefix + "member-01-negative-memory",
            {item.operation_id for item in steps},
        )
        self.assertEqual(
            steps[-4].event_kind,
            "historical_replay_obligations_resolved",
        )

    @patch(
        "axiom_rift.operations.fixed_hold_replay_workflow."
        "_protocol_activation_step_needed",
        return_value=True,
    )
    @patch(
        "axiom_rift.operations.fixed_hold_replay_workflow._member_completion",
        return_value=None,
    )
    def test_protocol_drift_is_repaired_before_the_first_job(
        self,
        _completion,
        _activation_needed,
    ) -> None:
        steps = operation_steps(SimpleNamespace(), self._design())
        self.assertEqual(len(steps), 40)
        self.assertEqual(
            steps[12].operation_id,
            "fixture-fixed-hold-replay-activate-current-v2-protocol",
        )
        self.assertEqual(
            steps[12].event_kind,
            "research_protocol_activated",
        )
        self.assertTrue(steps[13].operation_id.endswith("-declare-job"))

    @patch(
        "axiom_rift.operations.fixed_hold_replay_workflow."
        "_member_repair_chain_started",
        side_effect=lambda _writer, _design, member: member.ordinal == 1,
    )
    @patch(
        "axiom_rift.operations.fixed_hold_replay_workflow._member_completion",
        return_value=None,
    )
    def test_running_job_repair_remains_inside_the_strict_chain(
        self,
        _completion,
        _repair_started,
    ) -> None:
        steps = operation_steps(SimpleNamespace(), self._design())
        self.assertEqual(len(steps), 42)
        self.assertEqual(
            [item.event_kind for item in steps[15:18]],
            ["permit_issued", "repair_opened", "repair_closed"],
        )
        self.assertTrue(steps[18].operation_id.endswith("-complete-job"))


if __name__ == "__main__":
    unittest.main()
