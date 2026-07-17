from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import axiom_rift.operations.fixed_hold_replay_workflow as workflow
from axiom_rift.operations.fixed_hold_replay_workflow import (
    DIAGNOSE_STAGE,
    STUDY_CLOSE_STAGE,
    ReplayAxisAdmission,
    ReplayInitiativeLifecycle,
)
from axiom_rift.operations.replay_workflow_recovery import (
    diagnosis_architecture_review_trigger,
    require_borrowed_replay_admission,
    terminal_replay_reconstruction_allowed,
)
from axiom_rift.operations.replay_projection import with_scheduler_constraints
from axiom_rift.operations.strict_operation_chain import OperationStep
from axiom_rift.research.semantic_question import (
    SemanticQuestionLineageProposal,
    SemanticQuestionRelation,
)


MISSION_ID = "MIS-9001"
INITIATIVE_ID = "INI-9001"
STUDY_ID = "STU-9001"
PREFIX = "recovery-fixture-"
OBLIGATION_ID = "historical-replay-obligation:" + "a" * 64


class _Snapshot:
    def __init__(self, control: dict, index: object) -> None:
        self.control = control
        self.index = index

    def __enter__(self):
        return self.control, self.index

    def __exit__(self, *_exc_info: object) -> None:
        return None


def _spec(*, lifecycle=ReplayInitiativeLifecycle.OWN_BOUNDED_INITIATIVE):
    return SimpleNamespace(
        boundary=SimpleNamespace(sequence=100, event_id="0" * 64),
        initiative_id=INITIATIVE_ID,
        initiative_lifecycle=lifecycle,
        axis_admission=ReplayAxisAdmission.ADD_NEW_MECHANISM,
        mission_id=MISSION_ID,
        operation_prefix=PREFIX,
        study_id=STUDY_ID,
        target_obligation_id=OBLIGATION_ID,
    )


def _operation(suffix: str, event_kind: str, sequence: int, result: dict):
    return SimpleNamespace(
        authority_event_id=f"{sequence:064x}",
        authority_sequence=sequence,
        payload={"event_kind": event_kind, "result": result},
        status="success",
    )


class FixedHoldReplayRecoveryTests(unittest.TestCase):
    def test_permit_issue_is_rebound_to_exact_writer_transition(self) -> None:
        payload = {"permit_id": "a" * 64}
        permit = SimpleNamespace(payload=Mock(return_value=payload))
        operation = _operation(
            "study-permit",
            "permit_issued",
            101,
            {"permit": payload},
        )
        index = SimpleNamespace(get=Mock(return_value=operation))
        control = {
            "heads": {
                "journal": {
                    "event_id": operation.authority_event_id,
                    "sequence": operation.authority_sequence,
                }
            }
        }
        writer = SimpleNamespace(
            open_stable_index=Mock(return_value=_Snapshot(control, index))
        )

        transition = workflow._permit_issue_transition(
            writer,
            operation_id=PREFIX + "study-permit",
            permit=permit,
        )

        self.assertEqual(transition.event_id, operation.authority_event_id)
        self.assertEqual(transition.revision, operation.authority_sequence)
        self.assertFalse(transition.reused)
        self.assertEqual(transition.result, {"permit": payload})

        attacked = {
            "heads": {
                "journal": {
                    "event_id": "f" * 64,
                    "sequence": operation.authority_sequence,
                }
            }
        }
        writer.open_stable_index.return_value = _Snapshot(attacked, index)
        with self.assertRaisesRegex(RuntimeError, "Permit transition"):
            workflow._permit_issue_transition(
                writer,
                operation_id=PREFIX + "study-permit",
                permit=permit,
            )

    def test_study_permit_step_returns_authenticated_transition(self) -> None:
        permit = object()
        transition = workflow.TransitionResult(
            event_id="1" * 64,
            revision=101,
            reused=False,
            result={"permit": {}},
        )
        design = SimpleNamespace(
            members=(),
            spec=SimpleNamespace(operation_prefix=PREFIX),
        )
        writer = object()
        with (
            patch.object(workflow, "_study_permit", return_value=permit),
            patch.object(
                workflow,
                "_permit_issue_transition",
                return_value=transition,
            ) as bind,
        ):
            observed = workflow._apply_study_close_step(
                writer,
                design=design,
                step=OperationStep(
                    PREFIX + "study-permit",
                    "permit_issued",
                    STUDY_CLOSE_STAGE,
                ),
                repository_root=Path.cwd(),
                job_runner=Mock(),
                job_implementation_materializer=Mock(),
            )

        self.assertIs(observed, transition)
        bind.assert_called_once_with(
            writer,
            operation_id=PREFIX + "study-permit",
            permit=permit,
        )

    def test_diagnosis_replans_at_diagnosis_and_resolution_handoffs(self) -> None:
        close_event_id = "1" * 64
        initial_steps = (
            OperationStep(PREFIX + "close-study", "study_closed", STUDY_CLOSE_STAGE),
            OperationStep(
                PREFIX + "diagnose-study",
                "study_diagnosis_recorded",
                DIAGNOSE_STAGE,
            ),
            OperationStep(
                PREFIX + "resolve-replay",
                "historical_replay_obligations_resolved",
                DIAGNOSE_STAGE,
            ),
            OperationStep(
                PREFIX + "disposition-decision",
                "portfolio_decision_recorded",
                DIAGNOSE_STAGE,
            ),
        )
        handoff_steps = initial_steps[:3]
        cursor = workflow.OperationChainCursor(
            operation_prefix=PREFIX,
            predecessor_sequence=100,
            predecessor_event_id="0" * 64,
            steps=initial_steps,
            completed=1,
            current_sequence=101,
            current_event_id=close_event_id,
        )
        transitions = (
            workflow.TransitionResult(
                event_id="2" * 64,
                revision=102,
                reused=False,
                result={},
            ),
            workflow.TransitionResult(
                event_id="3" * 64,
                revision=103,
                reused=False,
                result={},
            ),
        )
        controls = iter(
            (
                {
                    "heads": {"journal": {"event_id": close_event_id}},
                    "next_action": {"study_close_record_id": "close-record"},
                    "revision": 101,
                },
                {"next_action": {"kind": "portfolio_decision"}},
            )
        )
        writer = SimpleNamespace(
            _require_study_close_delivery_guard=Mock(),
            open_stable_index=lambda: _Snapshot(next(controls), object()),
        )
        design = SimpleNamespace(
            members=(object(),),
            spec=_spec(
                lifecycle=ReplayInitiativeLifecycle.BORROW_ACTIVE_INITIATIVE
            ),
        )

        def refresh(_writer, _design, current):
            return current.replan(handoff_steps)

        apply_step = Mock(side_effect=transitions)
        with patch.multiple(
            workflow,
            _apply_diagnose_step=apply_step,
            _inspect_replay_cursor=Mock(return_value=cursor),
            _operation_record=Mock(
                return_value=SimpleNamespace(
                    authority_event_id=close_event_id,
                    authority_sequence=101,
                )
            ),
            _refresh_replay_cursor_plan=Mock(side_effect=refresh),
            _study_close_record=Mock(
                return_value=SimpleNamespace(record_id="close-record")
            ),
            require_stable_head=Mock(return_value={}),
            verify_diagnose_postconditions=Mock(
                return_value={
                    "architecture_review_trigger_id": None,
                    "axis_status": "pending_portfolio_decision",
                    "pending_replay_obligation_ids": [],
                    "replay_obligation_status": "satisfied",
                }
            ),
        ):
            summary = workflow.run_diagnose_stage(
                writer,
                design=design,
                study_close_event_id=close_event_id,
                study_close_revision=101,
            )

        self.assertEqual(apply_step.call_count, 2)
        self.assertEqual(summary["applied_step_count"], 2)
        self.assertEqual(
            summary["mode"],
            "replay_resolved_active_initiative_preserved",
        )

    def test_terminal_recovery_accepts_each_contiguous_exact_prefix(self) -> None:
        spec = _spec()
        diagnosis_id = "diagnosis:" + "b" * 64
        base_snapshot_id = "portfolio:" + "c" * 64
        disposition_snapshot_id = "portfolio:" + "d" * 64
        decision_id = "decision:" + "e" * 64
        axis_identity = "axis:" + "f" * 64
        operations = {
            PREFIX + "diagnose-study": _operation(
                "diagnose-study",
                "study_diagnosis_recorded",
                101,
                {
                    "architecture_review_trigger_id": None,
                    "study_diagnosis_id": diagnosis_id,
                },
            ),
            PREFIX + "resolve-replay": _operation(
                "resolve-replay",
                "historical_replay_obligations_resolved",
                102,
                {"satisfied_replay_obligation_ids": [OBLIGATION_ID]},
            ),
            PREFIX + "disposition-decision": _operation(
                "disposition-decision",
                "portfolio_decision_recorded",
                103,
                {"decision_id": decision_id},
            ),
            PREFIX + "disposition-snapshot": _operation(
                "disposition-snapshot",
                "portfolio_snapshot_recorded",
                104,
                {"portfolio_snapshot_id": disposition_snapshot_id},
            ),
            PREFIX + "close-initiative": _operation(
                "close-initiative",
                "initiative_closed",
                105,
                {"initiative_id": INITIATIVE_ID},
            ),
        }
        diagnosis = SimpleNamespace(
            authority_event_id=f"{101:064x}",
            authority_sequence=101,
            payload={
                "mission_id": MISSION_ID,
                "portfolio_snapshot_id": base_snapshot_id,
            },
            subject=f"Study:{STUDY_ID}",
        )
        decision = SimpleNamespace(
            payload={
                "chosen_option_id": "preserve",
                "options": [
                    {
                        "action": "preserve",
                        "option_id": "preserve",
                        "target_id": "AXS-9001",
                    }
                ],
                "portfolio_snapshot_id": base_snapshot_id,
                "replay_obligation_ids": [],
                "target_axis_identity": axis_identity,
            }
        )

        def index_for(operation_count: int):
            suffixes = tuple(operations)[:operation_count]
            present = {key: operations[key] for key in suffixes}
            return SimpleNamespace(
                get=lambda kind, record_id: (
                    diagnosis
                    if (kind, record_id) == ("study-diagnosis", diagnosis_id)
                    else decision
                    if (kind, record_id) == ("portfolio-decision", decision_id)
                    else present.get(record_id)
                    if kind == "operation"
                    else None
                )
            )

        terminal = SimpleNamespace(
            authority_event_id=f"{102:064x}",
            authority_sequence=102,
            payload={"obligation_id": OBLIGATION_ID},
            status="satisfied",
        )
        expected_actions = {
            2: {
                "kind": "portfolio_decision",
                "portfolio_snapshot_id": base_snapshot_id,
                "study_diagnosis_id": diagnosis_id,
            },
            3: {
                "action": "preserve",
                "decision_id": decision_id,
                "kind": "record_portfolio_snapshot",
                "portfolio_snapshot_id": base_snapshot_id,
                "target_axis_identity": axis_identity,
                "target_id": "AXS-9001",
            },
            4: {
                "kind": "portfolio_decision",
                "portfolio_snapshot_id": disposition_snapshot_id,
            },
            5: {
                "kind": "choose_next_initiative_or_terminal",
                "mission_id": MISSION_ID,
            },
        }
        with patch(
            "axiom_rift.operations.replay_workflow_recovery."
            "scheduler_constraints",
            return_value=None,
        ):
            for count, expected_action in expected_actions.items():
                with self.subTest(count=count):
                    self.assertTrue(
                        terminal_replay_reconstruction_allowed(
                            index_for(count),
                            spec,
                            terminal,
                            control={
                                "heads": {
                                    "journal": {
                                        "event_id": f"{100 + count:064x}",
                                        "sequence": 100 + count,
                                    }
                                },
                                "next_action": expected_action,
                            },
                        )
                    )

        historical_control = {
            "heads": {
                "journal": {
                    "event_id": f"{106:064x}",
                    "sequence": 106,
                }
            },
            "next_action": {"kind": "later_owner_action"},
        }
        self.assertTrue(
            terminal_replay_reconstruction_allowed(
                index_for(5),
                spec,
                terminal,
                control=historical_control,
            )
        )
        self.assertFalse(
            terminal_replay_reconstruction_allowed(
                index_for(5),
                spec,
                terminal,
                control={
                    **historical_control,
                    "heads": {
                        "journal": {
                            "event_id": f"{104:064x}",
                            "sequence": 104,
                        }
                    },
                },
            )
        )

        gap_index = index_for(4)
        original = operations.pop(PREFIX + "disposition-decision")
        try:
            self.assertFalse(
                terminal_replay_reconstruction_allowed(
                    index_for(4),
                    spec,
                    terminal,
                )
            )
        finally:
            operations[PREFIX + "disposition-decision"] = original
        self.assertIsNotNone(gap_index)

    def test_architecture_trigger_is_same_event_typed_and_exact(self) -> None:
        spec = _spec()
        diagnosis_id = "diagnosis:" + "1" * 64
        trigger_id = "architecture-review-trigger:" + "2" * 64
        event_id = "3" * 64
        snapshot_id = "portfolio:" + "4" * 64
        architecture_id = "architecture-family:" + "5" * 64
        operation = _operation(
            "diagnose-study",
            "study_diagnosis_recorded",
            101,
            {
                "architecture_review_trigger_id": trigger_id,
                "study_diagnosis_id": diagnosis_id,
            },
        )
        operation.authority_event_id = event_id
        diagnosis = SimpleNamespace(
            authority_event_id=event_id,
            authority_sequence=101,
            payload={
                "mission_id": MISSION_ID,
                "portfolio_snapshot_id": snapshot_id,
                "system_architecture_family": architecture_id,
            },
            subject=f"Study:{STUDY_ID}",
        )
        trigger = SimpleNamespace(
            authority_event_id=event_id,
            authority_sequence=101,
            payload={
                "diagnosis_ids": [diagnosis_id],
                "mission_id": MISSION_ID,
                "portfolio_snapshot_id": snapshot_id,
                "schema": "architecture_review_trigger.v1",
                "system_architecture_family": architecture_id,
            },
            record_id=trigger_id,
            status="required",
            subject=f"Mission:{MISSION_ID}",
        )
        records = {
            ("operation", PREFIX + "diagnose-study"): operation,
            ("study-diagnosis", diagnosis_id): diagnosis,
            ("architecture-review-trigger", trigger_id): trigger,
        }
        index = SimpleNamespace(
            get=lambda kind, record_id: records.get((kind, record_id))
        )
        self.assertEqual(
            diagnosis_architecture_review_trigger(index, spec),
            trigger_id,
        )
        attacks = (
            ("diagnosis_ids", diagnosis_id),
            ("portfolio_snapshot_id", "portfolio:" + "6" * 64),
        )
        for field, value in attacks:
            original = trigger.payload[field]
            trigger.payload[field] = value
            with self.subTest(field=field):
                with self.assertRaisesRegex(RuntimeError, "handoff is malformed"):
                    diagnosis_architecture_review_trigger(index, spec)
            trigger.payload[field] = original

    def test_borrowed_admission_requires_idle_exact_portfolio_action(self) -> None:
        spec = _spec(
            lifecycle=ReplayInitiativeLifecycle.BORROW_ACTIVE_INITIATIVE
        )
        portfolio_id = "portfolio:" + "7" * 64
        constraints = {
            "pending_replay_obligation_ids": [OBLIGATION_ID],
            "required_replay_priority": "p0",
        }
        diagnosis_id = "diagnosis:" + "6" * 64
        index = SimpleNamespace(
            event_head=lambda stream: (
                SimpleNamespace(
                    record_id=portfolio_id,
                    record_kind="portfolio-snapshot",
                )
                if stream == f"portfolio:{MISSION_ID}"
                else None
            ),
            get=lambda _kind, _record_id: None,
        )
        control = {
            "heads": {
                "journal": {
                    "event_id": spec.boundary.event_id,
                    "sequence": spec.boundary.sequence,
                }
            },
            "next_action": with_scheduler_constraints(
                {
                    "kind": "portfolio_decision",
                    "portfolio_snapshot_id": portfolio_id,
                    "study_diagnosis_id": diagnosis_id,
                },
                constraints,
            ),
            "scientific": {
                name: None
                for name in (
                    "active_batch",
                    "active_executable",
                    "active_holdout_evaluation",
                    "active_job",
                    "active_lineage",
                    "active_release",
                    "active_repair",
                    "active_study",
                )
            },
        }
        with patch(
            "axiom_rift.operations.replay_workflow_recovery."
            "scheduler_constraints",
            return_value=constraints,
        ):
            require_borrowed_replay_admission(
                control=control,
                index=index,
                spec=spec,
            )
            for attacked in (
                {**control, "next_action": {"kind": "review_architecture"}},
                {
                    **control,
                    "next_action": {
                        **control["next_action"],
                        "caller_note": "not typed decision authority",
                    },
                },
                {
                    **control,
                    "scientific": {
                        **control["scientific"],
                        "active_study": "STU-OTHER",
                    },
                },
                {
                    **control,
                    "heads": {
                        "journal": {
                            "event_id": "8" * 64,
                            "sequence": spec.boundary.sequence,
                        }
                    },
                },
            ):
                with self.subTest(attacked=attacked):
                    with self.assertRaises(RuntimeError):
                        require_borrowed_replay_admission(
                            control=attacked,
                            index=index,
                            spec=spec,
                        )

    def test_semantic_lineage_binds_permit_hash_and_study_open(self) -> None:
        core_id = "semantic-question-core:" + "9" * 64
        lineage = SemanticQuestionLineageProposal(
            predecessor_study_id="STU-8001",
            successor_study_id=STUDY_ID,
            predecessor_core_id=core_id,
            successor_core_id=core_id,
            relation=SemanticQuestionRelation.CONTINUATION,
            rationale="Continue the same estimand under corrected replay mechanics.",
            basis_record_ids=("study-close:STU-8001",),
        )
        spec = SimpleNamespace(
            initiative_id=INITIATIVE_ID,
            operation_prefix=PREFIX,
            permit_expiry_utc="2099-01-01T00:00:00Z",
            study_id=STUDY_ID,
        )
        design = SimpleNamespace(
            controlled_chassis=SimpleNamespace(
                architecture=SimpleNamespace(identity="architecture:fixture"),
                baseline_executable=SimpleNamespace(identity="executable:fixture"),
            ),
            expanded_snapshot=SimpleNamespace(identity="portfolio:fixture"),
            proposal={"fixture": True},
            question={"causal_question": "Does the corrected replay persist?"},
            replay_axis=SimpleNamespace(
                axis_id="AXS-9001",
                identity="axis:fixture",
            ),
            semantic_question_lineage=lineage,
            spec=spec,
            work_decision=SimpleNamespace(identity="decision:fixture"),
        )
        permit = object()
        writer = SimpleNamespace(
            issue_permit=Mock(return_value=permit),
            open_study=Mock(return_value=object()),
            study_input_hash=Mock(return_value="a" * 64),
        )
        self.assertIs(workflow._study_permit(writer, design), permit)
        self.assertIs(
            writer.study_input_hash.call_args.kwargs[
                "semantic_question_lineage"
            ],
            lineage,
        )
        with patch.object(workflow, "_permit_from_operation", return_value=permit):
            workflow._apply_study_close_step(
                writer,
                design=design,
                step=OperationStep(
                    PREFIX + "open-study",
                    "study_opened",
                    STUDY_CLOSE_STAGE,
                ),
                repository_root=Path.cwd(),
                job_runner=Mock(),
                job_implementation_materializer=Mock(),
            )
        self.assertIs(
            writer.open_study.call_args.kwargs["semantic_question_lineage"],
            lineage,
        )


if __name__ == "__main__":
    unittest.main()
