from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from axiom_rift.operations.fixed_hold_replay_workflow import (
    DIAGNOSE_STAGE,
    STUDY_CLOSE_STAGE,
    FixedHoldReplayMissionSpec,
    ReplayAuthorityBoundary,
    _member_repair_chain_complete,
    _protocol_activation_operation_id,
    _projection_payloads,
    _terminal_replay_reconstruction_allowed,
    fixed_hold_replay_batch_budget,
    fixed_hold_replay_job_budget,
    operation_steps,
)
from axiom_rift.operations.replay_projection import with_scheduler_constraints


class FixedHoldReplayWorkflowTests(unittest.TestCase):
    def test_terminal_reconstruction_requires_complete_exact_diagnosis_chain(
        self,
    ) -> None:
        spec = self._spec()
        expected_events = {
            "diagnose-study": "study_diagnosis_recorded",
            "resolve-replay": "historical_replay_obligations_resolved",
            "disposition-decision": "portfolio_decision_recorded",
            "disposition-snapshot": "portfolio_snapshot_recorded",
            "close-initiative": "initiative_closed",
        }
        records = {
            spec.operation_prefix + suffix: SimpleNamespace(
                status="success",
                payload={
                    "event_kind": event_kind,
                    "result": (
                        {"initiative_id": spec.initiative_id}
                        if suffix == "close-initiative"
                        else {}
                    ),
                },
            )
            for suffix, event_kind in expected_events.items()
        }
        index = SimpleNamespace(
            get=lambda _kind, record_id: records.get(record_id)
        )
        terminal = SimpleNamespace(status="satisfied")
        self.assertTrue(
            _terminal_replay_reconstruction_allowed(index, spec, terminal)
        )
        records.pop(spec.operation_prefix + "disposition-snapshot")
        self.assertFalse(
            _terminal_replay_reconstruction_allowed(index, spec, terminal)
        )
        self.assertFalse(
            _terminal_replay_reconstruction_allowed(
                index,
                spec,
                SimpleNamespace(status="pending"),
            )
        )

    def test_exhausted_replay_queue_omits_scheduler_constraint_fields(
        self,
    ) -> None:
        base = {
            "kind": "choose_next_initiative_or_terminal",
            "mission_id": "MIS-9001",
        }
        self.assertEqual(with_scheduler_constraints(base, None), base)
        self.assertEqual(
            with_scheduler_constraints(
                base,
                {
                    "pending_replay_obligation_ids": ["obligation-a"],
                    "required_replay_priority": "p1",
                },
            ),
            {
                **base,
                "pending_replay_obligation_ids": ["obligation-a"],
                "required_replay_priority": "p1",
            },
        )

    def _spec(self) -> FixedHoldReplayMissionSpec:
        return FixedHoldReplayMissionSpec(
            mission_id="MIS-9001",
            initiative_id="INI-9001",
            study_id="STU-9001",
            batch_display_id="BAT-9001",
            axis_id="axis-fixture-replay",
            bridge_axis_id="axis-fixture-source",
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

    def test_family_cache_budget_does_not_multiply_producer_work(self) -> None:
        producer = SimpleNamespace(
            job_plan=SimpleNamespace(produces_family_cache=True)
        )
        consumers = tuple(
            SimpleNamespace(
                job_plan=SimpleNamespace(produces_family_cache=False)
            )
            for _ in range(11)
        )
        self.assertEqual(
            fixed_hold_replay_job_budget(producer),
            {"compute_seconds": 3_600, "wall_seconds": 5_400},
        )
        self.assertEqual(
            fixed_hold_replay_job_budget(consumers[0]),
            {"compute_seconds": 900, "wall_seconds": 1_440},
        )
        self.assertEqual(
            fixed_hold_replay_batch_budget((producer, *consumers)),
            {"compute_seconds": 13_500, "wall_seconds": 21_240},
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
            _protocol_activation_operation_id(self._design()),
        )
        self.assertEqual(
            steps[12].event_kind,
            "research_protocol_activated",
        )
        self.assertTrue(steps[13].operation_id.endswith("-declare-job"))

    @patch(
        "axiom_rift.operations.fixed_hold_replay_workflow."
        "_recorded_protocol_activation_operation_ids",
        return_value=(
            "fixture-fixed-hold-replay-activate-current-v2-protocol",
        ),
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
    def test_protocol_rebind_preserves_prior_activation_in_strict_chain(
        self,
        _completion,
        _activation_needed,
        _recorded_activations,
    ) -> None:
        design = self._design()
        steps = operation_steps(SimpleNamespace(), design)
        self.assertEqual(len(steps), 41)
        self.assertEqual(
            tuple(step.operation_id for step in steps[12:14]),
            (
                "fixture-fixed-hold-replay-activate-current-v2-protocol",
                _protocol_activation_operation_id(design),
            ),
        )
        self.assertTrue(steps[14].operation_id.endswith("-declare-job"))

    @patch(
        "axiom_rift.operations.fixed_hold_replay_workflow."
        "_member_repair_chain_complete",
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

    def test_component_projection_does_not_scan_growing_work_history(self) -> None:
        executable = SimpleNamespace(
            to_identity_payload=lambda: {"schema": "executable_spec.v1"}
        )
        index = SimpleNamespace(records_by_kind=Mock(return_value=()))
        result = _projection_payloads(
            index,
            (SimpleNamespace(executable=executable),),
        )
        self.assertEqual(result, ({"schema": "executable_spec.v1"},))
        index.records_by_kind.assert_called_once_with("component-manifest")

    @patch("axiom_rift.operations.fixed_hold_replay_workflow.LocalIndex")
    def test_partial_repair_chain_requires_exact_resume(self, local_index) -> None:
        design = self._design()
        stem = design.spec.operation_prefix + design.members[0].label
        permit = SimpleNamespace(
            status="success",
            payload={"event_kind": "permit_issued"},
        )
        projected = local_index.return_value.__enter__.return_value
        projected.get.side_effect = lambda _kind, record_id: (
            permit if record_id == stem + "-repair-permit" else None
        )
        with self.assertRaisesRegex(RuntimeError, "Repair is incomplete"):
            _member_repair_chain_complete(
                SimpleNamespace(index_path="fixture.sqlite"),
                design,
                design.members[0],
            )


if __name__ == "__main__":
    unittest.main()
