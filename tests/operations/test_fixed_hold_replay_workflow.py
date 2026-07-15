from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import axiom_rift.operations.fixed_hold_replay_workflow as workflow_module

from axiom_rift.operations.fixed_hold_replay_workflow import (
    DIAGNOSE_STAGE,
    STUDY_CLOSE_STAGE,
    FixedHoldReplayDesign,
    FixedHoldReplayMissionSpec,
    ReplayAuthorityBoundary,
    ReplayInterpretation,
    _accepted_decision_review_mode,
    _all_member_repair_chains,
    _canonical_statistical_family_ids,
    _member_repair_chain_complete,
    _protocol_activation_operation_id,
    _projection_payloads,
    _recorded_protocol_activation_operation_ids,
    _require_scientific_study_close_projection,
    _study_close_record,
    _terminal_replay_reconstruction_allowed,
    _workflow_job_declarations,
    build_fixed_hold_replay_design,
    fixed_hold_replay_batch_budget,
    fixed_hold_replay_job_budget,
    inspect_replay_prefix,
    operation_steps,
)
from axiom_rift.operations.replay_projection import with_scheduler_constraints
from axiom_rift.operations.strict_operation_chain import OperationStep
from axiom_rift.research.historical_family_binding import (
    ControlBinding,
    HistoricalFamilyAuthority,
    HistoricalFamilySpec,
    HistoricalMemberSpec,
)


class _StableSnapshot:
    def __init__(self, control: dict, index: object) -> None:
        self.control = control
        self.index = index

    def __enter__(self):
        return self.control, self.index

    def __exit__(self, *_exc_info: object) -> None:
        return None


def _snapshot_writer(index: object, *, control: dict | None = None):
    stable_control = {} if control is None else control
    return SimpleNamespace(
        open_stable_index=lambda: _StableSnapshot(stable_control, index)
    )


def _empty_workflow_writer():
    authority_digest = "a" * 64
    protocol_record_id = "protocol-activation:" + "b" * 64
    protocol_head = SimpleNamespace(
        record_kind="research-protocol-activation",
        record_id=protocol_record_id,
    )
    protocol = SimpleNamespace(
        kind="research-protocol-activation",
        payload={
            "authority_manifest_digest": authority_digest,
            "protocol": "scientific_adjudication_v2",
            "validator_id": workflow_module.SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
        },
        status="active",
    )

    class EmptyIndex:
        @staticmethod
        def event_head(stream: str):
            return protocol_head if stream == "research-protocol:scientific" else None

        @staticmethod
        def get(_kind: str, record_id: str):
            return protocol if record_id == protocol_record_id else None

        @staticmethod
        def records_by_kind_prefix(_kind: str, _prefix: str):
            return ()

    return _snapshot_writer(
        EmptyIndex(),
        control={
            "authority": {"manifest_digest": authority_digest},
            "heads": {"journal": {"sequence": 100}},
            "scientific": {"active_batch": None},
        },
    )


class _AcceptedHistoricalFamilyAuthorityReached(RuntimeError):
    """Test sentinel reached only after the durable family gate passes."""


class FixedHoldReplayWorkflowTests(unittest.TestCase):
    def test_candidate_postcondition_uses_exact_executable_history(self) -> None:
        executable_id = "executable:" + "a" * 64
        stream = f"candidate:{executable_id}"
        candidate = SimpleNamespace(
            event_stream=stream,
            kind="candidate",
            record_id="candidate:" + "b" * 64,
            subject=f"Executable:{executable_id}",
        )
        head = SimpleNamespace(
            record_id="disposition:" + "c" * 64,
            record_kind="candidate-disposition",
        )
        head_record = SimpleNamespace(event_stream=stream)

        class ExactIndex:
            def event_head(self, requested_stream: str):
                self.requested_stream = requested_stream
                return head

            def get(self, kind: str, record_id: str):
                self.requested_head = (kind, record_id)
                return head_record

            def records_by_fingerprint(self, fingerprint: str):
                self.requested_fingerprint = fingerprint
                return (candidate,)

            def records_by_kind(self, _kind: str):
                raise AssertionError("candidate postcondition scanned global history")

        index = ExactIndex()
        writer = _snapshot_writer(
            index,
            control={
                "scientific": {
                    "active_holdout_evaluation": None,
                    "holdout_reveals": 0,
                }
            },
        )
        design = SimpleNamespace(
            members=(
                SimpleNamespace(executable=SimpleNamespace(identity=executable_id)),
            )
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "created candidate or holdout authority",
        ):
            workflow_module._verify_no_candidate_or_holdout(writer, design)
        self.assertEqual(index.requested_stream, stream)
        self.assertEqual(
            index.requested_head,
            (head.record_kind, head.record_id),
        )
        self.assertEqual(index.requested_fingerprint, "a" * 64)

    def test_incomplete_scientific_recomputation_preserves_exact_deferral(self) -> None:
        completion = SimpleNamespace(record_id="completion:" + "a" * 64)
        interpretation = ReplayInterpretation(
            all_criteria_recomputed=False,
            close_outcome="not_evaluable",
            diagnosis_state=workflow_module.EvidenceState.NOT_IDENTIFIABLE,
            disposition=workflow_module.PortfolioAction.PRESERVE,
            reason_code="original_criterion_recomputation_incomplete",
        )
        _require_scientific_study_close_projection(
            close_record=SimpleNamespace(status="not_evaluable"),
            completion=completion,
            study_kpi=SimpleNamespace(
                status="not_evaluable",
                payload={"completion_record_id": completion.record_id},
            ),
            interpretation=interpretation,
        )

    def test_incomplete_scientific_close_drift_fails_closed(self) -> None:
        completion = SimpleNamespace(record_id="completion:" + "b" * 64)
        valid = ReplayInterpretation(
            all_criteria_recomputed=False,
            close_outcome="not_evaluable",
            diagnosis_state=workflow_module.EvidenceState.NOT_IDENTIFIABLE,
            disposition=workflow_module.PortfolioAction.PRESERVE,
            reason_code="original_criterion_recomputation_unavailable",
        )
        cases = (
            (
                SimpleNamespace(status="pruned"),
                SimpleNamespace(
                    status="not_evaluable",
                    payload={"completion_record_id": completion.record_id},
                ),
                valid,
                "projection drifted",
            ),
            (
                SimpleNamespace(status="not_evaluable"),
                SimpleNamespace(
                    status="not_evaluable",
                    payload={"completion_record_id": "completion:" + "c" * 64},
                ),
                valid,
                "projection drifted",
            ),
            (
                SimpleNamespace(status="pruned"),
                SimpleNamespace(
                    status="pruned",
                    payload={"completion_record_id": completion.record_id},
                ),
                ReplayInterpretation(
                    all_criteria_recomputed=False,
                    close_outcome="pruned",
                    diagnosis_state=workflow_module.EvidenceState.NOT_IDENTIFIABLE,
                    disposition=workflow_module.PortfolioAction.PRUNE,
                    reason_code="original_criterion_recomputation_incomplete",
                ),
                "deferral boundary",
            ),
        )
        for close_record, study_kpi, interpretation, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(RuntimeError, message):
                    _require_scientific_study_close_projection(
                        close_record=close_record,
                        completion=completion,
                        study_kpi=study_kpi,
                        interpretation=interpretation,
                    )

    def test_workflow_projection_reads_have_no_read_write_index_open(self) -> None:
        path = Path(workflow_module.__file__).resolve()
        tree = ast.parse(path.read_text(encoding="ascii"))
        direct_writable_opens = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "LocalIndex"
        ]
        read_only_opens = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "open_read_only"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "LocalIndex"
        ]
        self.assertEqual(direct_writable_opens, [])
        self.assertEqual(read_only_opens, [])
        self.assertNotIn("read_control", path.read_text(encoding="ascii"))
        self.assertNotIn("index_path", path.read_text(encoding="ascii"))

    def test_accepted_legacy_decision_identity_is_preserved_but_new_work_reviews(
        self,
    ) -> None:
        records = {}
        index = SimpleNamespace(
            get=lambda kind, record_id: records.get((kind, record_id))
        )
        operation_id = "replay-bridge-decision"
        self.assertIsNone(_accepted_decision_review_mode(index, operation_id))

        decision_id = "decision:" + "a" * 64
        records[("operation", operation_id)] = SimpleNamespace(
            status="success",
            payload={
                "event_kind": "portfolio_decision_recorded",
                "result": {"decision_id": decision_id},
            },
        )
        records[("portfolio-decision", decision_id)] = SimpleNamespace(
            payload={"schema": "portfolio_decision.v2"}
        )
        self.assertFalse(_accepted_decision_review_mode(index, operation_id))

        records[("portfolio-decision", decision_id)] = SimpleNamespace(
            payload={
                "quant_team_review": {
                    "schema": "quant_team_decision_review.v1"
                }
            }
        )
        self.assertTrue(_accepted_decision_review_mode(index, operation_id))

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

    def _historical_family(
        self,
        *,
        parameter_tag: str = "authority",
    ) -> HistoricalFamilySpec:
        references = tuple(
            f"executable:{ordinal:064x}" for ordinal in range(1, 5)
        )
        members = tuple(
            HistoricalMemberSpec(
                ordinal=ordinal,
                configuration_id=f"configuration-{ordinal}",
                historical_reference_executable_id=references[ordinal - 1],
                parameters={
                    "parameter_tag": parameter_tag,
                    "slot": ordinal,
                },
            )
            for ordinal in range(1, 5)
        )
        opposite_indices = (1, 0, 3, 2)
        feature_indices = (2, 2, 0, 0)
        controls = tuple(
            ControlBinding(
                subject_historical_executable_id=reference,
                opposite_historical_executable_id=(
                    references[opposite_indices[index]]
                ),
                feature_historical_executable_ids=(
                    references[feature_indices[index]],
                ),
            )
            for index, reference in enumerate(references)
        )
        return HistoricalFamilySpec(
            original_study_id="STU-8001",
            original_batch_id="batch:" + "8" * 64,
            target_historical_executable_id=references[-1],
            members=members,
            controls=controls,
        )

    def _run_historical_family_authority_gate(
        self,
        *,
        definition_family: object,
        authority: HistoricalFamilyAuthority,
        authority_record: object | None,
        caller_manifest: dict[str, object],
    ) -> None:
        spec = self._spec()
        snapshot_id = "portfolio-snapshot:" + "4" * 64
        source_axis = SimpleNamespace(axis_id=spec.bridge_axis_id)
        snapshot = SimpleNamespace(
            payload={"axes": [{"axis_id": spec.bridge_axis_id}]},
            record_id=snapshot_id,
        )
        obligation = SimpleNamespace(
            criterion_ids=("criterion-a",),
            identity=spec.target_obligation_id,
            original_executable_id=(
                authority.family.target_historical_executable_id
            ),
            original_study_id=spec.original_study_id,
        )
        head = SimpleNamespace(status="pending")
        members = tuple(
            SimpleNamespace(
                executable=SimpleNamespace(
                    identity=f"executable:{100 + ordinal:064x}"
                ),
                historical_reference_executable_id=(
                    authority.family.members[ordinal - 1]
                    .historical_reference_executable_id
                ),
                job_plan=SimpleNamespace(
                    definition=SimpleNamespace(family=definition_family)
                ),
                ordinal=ordinal,
            )
            for ordinal in range(1, 5)
        )

        class GateIndex:
            @staticmethod
            def get(kind: str, record_id: str):
                if (kind, record_id) == (
                    "portfolio-snapshot",
                    snapshot_id,
                ):
                    return snapshot
                if (kind, record_id) == (
                    "historical-family-authority",
                    authority.identity,
                ):
                    return authority_record
                return None

        writer = _snapshot_writer(GateIndex())
        patches = {
            "_accepted_decision_review_mode": Mock(return_value=False),
            "_base_snapshot_id": Mock(return_value=snapshot_id),
            "_projection_payloads": Mock(return_value=()),
            "_terminal_replay_reconstruction_allowed": Mock(
                return_value=False
            ),
            "component_surface_registry": Mock(return_value={}),
            "effective_axis_resolutions": Mock(
                return_value=(
                    SimpleNamespace(
                        status=workflow_module.EffectiveAxisStatus.SELECTABLE
                    ),
                )
            ),
            "obligation_heads": Mock(return_value=((obligation, head),)),
            "portfolio_axes_from_projection": Mock(
                return_value=(source_axis,)
            ),
            "PortfolioAxis": Mock(
                side_effect=_AcceptedHistoricalFamilyAuthorityReached
            ),
        }
        with patch.multiple(workflow_module, **patches):
            build_fixed_hold_replay_design(
                writer,
                spec=spec,
                members=members,
                target_executable_id=members[-1].executable.identity,
                controlled_chassis=SimpleNamespace(
                    architecture=SimpleNamespace(
                        identity="fixture-architecture"
                    ),
                    changed_domains=(),
                    controlled_domains=(),
                ),
                historical_family_manifest=caller_manifest,
                historical_family_authority_id=authority.identity,
                criterion_ids=("criterion-a",),
                causal_question="fixture causal question",
                mechanism_family="fixture mechanism",
                why_now="fixture authority regression",
                stop_or_reopen_condition="stop after exact family",
            )

    def test_design_requires_one_accepted_historical_family_authority(
        self,
    ) -> None:
        family = self._historical_family()
        authority = HistoricalFamilyAuthority(
            replay_obligation_id=self._spec().target_obligation_id,
            family=family,
            reconstruction_source_path=(
                "src/axiom_rift/research/historical_fixture.py"
            ),
            reconstruction_source_sha256="5" * 64,
        )
        accepted = SimpleNamespace(
            fingerprint=authority.identity.removeprefix(
                "historical-family-authority:"
            ),
            payload=authority.to_identity_payload(),
            record_id=authority.identity,
            status="accepted",
            subject=f"ReplayObligation:{authority.replay_obligation_id}",
        )
        with self.assertRaises(_AcceptedHistoricalFamilyAuthorityReached):
            self._run_historical_family_authority_gate(
                definition_family=family,
                authority=authority,
                authority_record=accepted,
                caller_manifest=family.manifest(),
            )

        for record in (
            None,
            SimpleNamespace(
                fingerprint=accepted.fingerprint,
                payload=accepted.payload,
                record_id=accepted.record_id,
                status="proposed",
                subject=accepted.subject,
            ),
        ):
            with self.subTest(record=record):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "historical family authority|durable authority",
                ):
                    self._run_historical_family_authority_gate(
                        definition_family=family,
                        authority=authority,
                        authority_record=record,
                        caller_manifest=family.manifest(),
                    )

    def test_design_rejects_legacy_or_caller_family_bypass(self) -> None:
        family = self._historical_family()
        authority = HistoricalFamilyAuthority(
            replay_obligation_id=self._spec().target_obligation_id,
            family=family,
            reconstruction_source_path=(
                "src/axiom_rift/research/historical_fixture.py"
            ),
            reconstruction_source_sha256="5" * 64,
        )
        accepted = SimpleNamespace(
            fingerprint=authority.identity.removeprefix(
                "historical-family-authority:"
            ),
            payload=authority.to_identity_payload(),
            record_id=authority.identity,
            status="accepted",
            subject=f"ReplayObligation:{authority.replay_obligation_id}",
        )
        with self.assertRaisesRegex(RuntimeError, "Writer-bound family data"):
            self._run_historical_family_authority_gate(
                definition_family=SimpleNamespace(
                    manifest=lambda: family.manifest()
                ),
                authority=authority,
                authority_record=accepted,
                caller_manifest=family.manifest(),
            )

        caller_family = self._historical_family(
            parameter_tag="caller-substitution"
        )
        with self.assertRaisesRegex(RuntimeError, "durable authority"):
            self._run_historical_family_authority_gate(
                definition_family=family,
                authority=authority,
                authority_record=accepted,
                caller_manifest=caller_family.manifest(),
            )

    @patch(
        "axiom_rift.operations.fixed_hold_replay_workflow._member_completion",
        return_value=None,
    )
    def test_operation_plan_is_one_exact_two_stage_chain(self, _completion) -> None:
        steps = operation_steps(_empty_workflow_writer(), self._design())
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

    @patch(
        "axiom_rift.operations.fixed_hold_replay_workflow._member_completion",
        return_value=None,
    )
    def test_operation_plan_preregisters_family_before_any_job(
        self,
        _completion,
    ) -> None:
        design = self._design()
        operation_ids = tuple(
            step.operation_id
            for step in operation_steps(_empty_workflow_writer(), design)
        )
        positions = {
            operation_id: index
            for index, operation_id in enumerate(operation_ids)
        }
        prefix = design.spec.operation_prefix
        register_positions = tuple(
            positions[prefix + member.label + "-register-trial"]
            for member in design.members
        )
        declare_positions = tuple(
            positions[prefix + member.label + "-declare-job"]
            for member in design.members
        )
        assert max(register_positions) < min(declare_positions)
        for current, following in zip(
            design.members[:-1],
            design.members[1:],
            strict=True,
        ):
            assert positions[
                prefix + current.label + "-register-trial"
            ] < positions[prefix + current.label + "-declare-job"]
            assert positions[
                prefix + current.label + "-declare-job"
            ] < positions[prefix + current.label + "-judge-job"]
            assert positions[
                prefix + current.label + "-judge-job"
            ] < positions[prefix + following.label + "-declare-job"]

    def test_prefix_inspection_shares_one_authenticated_snapshot(self) -> None:
        writer = _empty_workflow_writer()
        writer.journal = object()
        original_open = writer.open_stable_index
        open_count = 0

        def open_once():
            nonlocal open_count
            open_count += 1
            return original_open()

        writer.open_stable_index = open_once
        with patch(
            "axiom_rift.operations.fixed_hold_replay_workflow."
            "inspect_operation_prefix",
            return_value=0,
        ) as inspect:
            completed, steps = inspect_replay_prefix(writer, self._design())

        self.assertEqual(completed, 0)
        self.assertTrue(steps)
        self.assertEqual(open_count, 1)
        inspect.assert_called_once()

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

    def test_batch_family_is_canonical_without_reordering_execution(self) -> None:
        execution_ids = tuple(
            "executable:" + character * 64
            for character in ("d", "a", "c", "b")
        )
        definition = SimpleNamespace(
            identity="definition:fixture",
            prospective_executable_ids=execution_ids,
        )
        members = tuple(
            SimpleNamespace(
                executable=SimpleNamespace(identity=executable_id),
                job_plan=SimpleNamespace(definition=definition),
                ordinal=ordinal,
            )
            for ordinal, executable_id in enumerate(execution_ids, start=1)
        )
        canonical_ids = tuple(sorted(execution_ids))

        self.assertEqual(
            _canonical_statistical_family_ids(members),
            canonical_ids,
        )
        design_values = {
            "spec": self._spec(),
            "base_snapshot_id": "portfolio:fixture",
            "prior_axes": (),
            "replay_axis": None,
            "bridge_decision": None,
            "expanded_snapshot": None,
            "work_decision": None,
            "members": members,
            "target_executable_id": execution_ids[-1],
            "question": {},
            "proposal": {},
            "batch_spec": SimpleNamespace(
                concurrent_family=SimpleNamespace(
                    executable_ids=canonical_ids,
                )
            ),
            "controlled_chassis": None,
            "criterion_ids": ("criterion-a",),
        }
        design = FixedHoldReplayDesign(**design_values)
        self.assertEqual(
            tuple(member.executable.identity for member in design.members),
            execution_ids,
        )

        design_values["batch_spec"] = SimpleNamespace(
            concurrent_family=SimpleNamespace(
                executable_ids=execution_ids,
            )
        )
        with self.assertRaisesRegex(ValueError, "statistical family"):
            FixedHoldReplayDesign(**design_values)

    def test_failed_member_adds_memory_without_changing_replay_coverage(self) -> None:
        design = self._design()
        failed = SimpleNamespace(
            payload={"scientific": {"verdict": "failed"}}
        )
        target = SimpleNamespace(
            payload={"scientific": {"verdict": "not_evaluable"}}
        )

        def completion(_writer, _design, member, **_snapshot):
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
            steps = operation_steps(_empty_workflow_writer(), design)
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
        steps = operation_steps(_empty_workflow_writer(), self._design())
        self.assertEqual(len(steps), 40)
        operation_ids = tuple(step.operation_id for step in steps)
        activation_id = _protocol_activation_operation_id(self._design())
        activation_index = operation_ids.index(activation_id)
        register_index = operation_ids.index(
            self._design().spec.operation_prefix
            + self._design().members[0].label
            + "-register-trial"
        )
        declare_index = operation_ids.index(
            self._design().spec.operation_prefix
            + self._design().members[0].label
            + "-declare-job"
        )
        self.assertEqual(
            steps[activation_index].operation_id,
            activation_id,
        )
        self.assertEqual(
            steps[activation_index].event_kind,
            "research_protocol_activated",
        )
        self.assertLess(activation_index, register_index)
        self.assertLess(register_index, declare_index)

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
        steps = operation_steps(_empty_workflow_writer(), design)
        self.assertEqual(len(steps), 41)
        operation_ids = tuple(step.operation_id for step in steps)
        prior_id = "fixture-fixed-hold-replay-activate-current-v2-protocol"
        current_id = _protocol_activation_operation_id(design)
        prior_index = operation_ids.index(prior_id)
        current_index = operation_ids.index(current_id)
        register_index = operation_ids.index(
            design.spec.operation_prefix
            + design.members[0].label
            + "-register-trial"
        )
        self.assertEqual(
            tuple(
                step.operation_id
                for step in steps[prior_index : current_index + 1]
            ),
            (
                prior_id,
                current_id,
            ),
        )
        self.assertLess(current_index, register_index)

    @patch(
        "axiom_rift.operations.fixed_hold_replay_workflow."
        "_all_member_repair_chains",
    )
    @patch(
        "axiom_rift.operations.fixed_hold_replay_workflow._member_completion",
        return_value=None,
    )
    def test_running_job_repair_remains_inside_the_strict_chain(
        self,
        _completion,
        repair_chains,
    ) -> None:
        design = self._design()
        member = design.members[0]
        stem = design.spec.operation_prefix + member.label
        repair_chains.return_value = {
            item.ordinal: (
                (
                    OperationStep(
                        stem + "-repair-permit",
                        "permit_issued",
                        STUDY_CLOSE_STAGE,
                    ),
                    OperationStep(
                        stem + "-open-repair",
                        "repair_opened",
                        STUDY_CLOSE_STAGE,
                    ),
                    OperationStep(
                        stem + "-close-repair",
                        "repair_closed",
                        STUDY_CLOSE_STAGE,
                    ),
                    OperationStep(
                        stem + "-resume-repaired-job",
                        "job_repaired_execution_resumed",
                        STUDY_CLOSE_STAGE,
                    ),
                )
                if item.ordinal == member.ordinal
                else ()
            )
            for item in design.members
        }
        steps = operation_steps(_empty_workflow_writer(), design)
        self.assertEqual(len(steps), 43)
        operation_ids = tuple(item.operation_id for item in steps)
        repair_index = operation_ids.index(stem + "-repair-permit")
        self.assertEqual(
            [
                item.event_kind
                for item in steps[repair_index : repair_index + 4]
            ],
            [
                "permit_issued",
                "repair_opened",
                "repair_closed",
                "job_repaired_execution_resumed",
            ],
        )
        self.assertEqual(
            steps[repair_index + 4].operation_id,
            stem + "-complete-job",
        )

    @patch(
        "axiom_rift.operations.fixed_hold_replay_workflow."
        "_all_member_repair_chains",
    )
    @patch(
        "axiom_rift.operations.fixed_hold_replay_workflow._member_completion",
        return_value=None,
    )
    def test_unrecovered_repair_stops_execution_without_abandoning_family_record(
        self,
        _completion,
        repair_chains,
    ) -> None:
        design = self._design()
        member = design.members[1]
        stem = design.spec.operation_prefix + member.label
        repair_chains.return_value = {
            item.ordinal: (
                (
                    OperationStep(
                        stem + "-repair-permit",
                        "permit_issued",
                        STUDY_CLOSE_STAGE,
                    ),
                    OperationStep(
                        stem + "-open-repair",
                        "repair_opened",
                        STUDY_CLOSE_STAGE,
                    ),
                    OperationStep(
                        stem + "-conclude-repair",
                        "repair_concluded_unrecovered",
                        STUDY_CLOSE_STAGE,
                    ),
                )
                if item.ordinal == member.ordinal
                else ()
            )
            for item in design.members
        }
        steps = operation_steps(_empty_workflow_writer(), design)
        operation_ids = {step.operation_id for step in steps}
        prefix = design.spec.operation_prefix
        self.assertIn(prefix + "member-02-register-trial", operation_ids)
        self.assertIn(prefix + "member-03-register-trial", operation_ids)
        self.assertIn(prefix + "member-04-register-trial", operation_ids)
        self.assertIn(prefix + "member-02-complete-job", operation_ids)
        self.assertIn(prefix + "member-02-judge-job", operation_ids)
        self.assertNotIn(prefix + "member-03-declare-job", operation_ids)
        self.assertEqual(
            steps[-4].event_kind,
            "historical_replay_obligations_deferred",
        )

    def test_component_projection_does_not_scan_growing_work_history(self) -> None:
        executable = SimpleNamespace(
            to_identity_payload=lambda: {"schema": "executable_spec.v1"}
        )
        surface = "architecture-component-surface:" + "a" * 64
        component_payload = {"schema": "component_manifest_projection.v1"}
        index = SimpleNamespace(
            component_manifests_by_surfaces=Mock(
                return_value=(SimpleNamespace(payload=component_payload),)
            )
        )
        result = _projection_payloads(
            index,
            (SimpleNamespace(executable=executable),),
            (
                {
                    "architecture_chassis": {
                        "schema": "architecture_chassis.v2",
                        "roles": {
                            "decision": {
                                "component_semantic_surfaces": [surface]
                            }
                        },
                    }
                },
            ),
        )
        self.assertEqual(
            result,
            ({"schema": "executable_spec.v1"}, component_payload),
        )
        index.component_manifests_by_surfaces.assert_called_once_with(
            "architecture_role",
            (surface,),
        )

    def test_protocol_activation_lookup_is_workflow_prefix_bounded(
        self,
    ) -> None:
        projected = Mock()
        projected.records_by_kind_prefix.return_value = ()
        design = self._design()

        self.assertEqual(
            _recorded_protocol_activation_operation_ids(
                _snapshot_writer(projected),
                design,
            ),
            (),
        )
        projected.records_by_kind_prefix.assert_called_once_with(
            "operation",
            design.spec.operation_prefix,
        )
        projected.records_by_kind.assert_not_called()

    def test_workflow_job_declarations_use_exact_operation_and_job_keys(
        self,
    ) -> None:
        member = SimpleNamespace(
            executable=SimpleNamespace(identity="executable:" + "4" * 64),
            label="member-01",
            ordinal=1,
        )
        design = SimpleNamespace(spec=self._spec(), members=(member,))
        batch_id = "batch:" + "0" * 64
        job_hash = "1" * 64
        job_id = "job:" + job_hash
        operation_id = (
            design.spec.operation_prefix + member.label + "-declare-job"
        )
        operation = SimpleNamespace(
            payload={
                "event_kind": "job_declared",
                "result": {"job_hash": job_hash, "job_id": job_id},
            },
            status="success",
        )
        declaration = SimpleNamespace(
            payload={
                "batch_id": batch_id,
                "mission_id": design.spec.mission_id,
                "spec": {
                    "evidence_subject": {
                        "id": member.executable.identity,
                        "kind": "Executable",
                    }
                },
                "study_id": design.spec.study_id,
            },
            record_id=job_id,
            status="declared",
        )
        index = SimpleNamespace(
            get=Mock(
                side_effect=lambda kind, record_id: (
                    operation
                    if (kind, record_id) == ("operation", operation_id)
                    else declaration
                    if (kind, record_id) == ("job-declared", job_id)
                    else None
                )
            ),
            records_by_kind=Mock(),
        )

        self.assertEqual(
            _workflow_job_declarations(
                index,
                design,
                batch_id=batch_id,
            ),
            (declaration,),
        )
        index.records_by_kind.assert_not_called()

    def test_study_close_lookup_is_subject_status_bounded(
        self,
    ) -> None:
        design = self._design()
        operation = SimpleNamespace(
            authority_event_id="2" * 64,
            authority_sequence=123,
            payload={"result": {"outcome": "preserved"}},
            status="success",
        )
        close = SimpleNamespace(
            authority_event_id="2" * 64,
            authority_sequence=123,
            kind="study-close",
            record_id="3" * 64,
        )
        projected = Mock()
        projected.get.return_value = operation
        projected.records_by_subject_status.return_value = (close,)

        self.assertIs(
            _study_close_record(
                _snapshot_writer(projected),
                design,
            ),
            close,
        )
        projected.records_by_subject_status.assert_called_once_with(
            f"Study:{design.spec.study_id}",
            "preserved",
        )
        projected.records_by_kind.assert_not_called()

    def test_partial_repair_chain_requires_exact_resume(self) -> None:
        design = self._design()
        stem = design.spec.operation_prefix + design.members[0].label
        permit = SimpleNamespace(
            authority_sequence=100,
            record_id=stem + "-repair-permit",
            status="success",
            payload={"event_kind": "permit_issued"},
        )
        projected = Mock()
        projected.get.side_effect = lambda _kind, record_id: (
            permit if record_id == stem + "-repair-permit" else None
        )
        projected.records_by_kind_prefix.return_value = ()
        with self.assertRaisesRegex(RuntimeError, "Repair is incomplete"):
            _member_repair_chain_complete(
                _snapshot_writer(projected),
                design,
                design.members[0],
            )

    def test_failed_repair_attempt_stays_in_strict_chain(self) -> None:
        design = self._design()
        member = design.members[0]
        stem = design.spec.operation_prefix + member.label
        repair_id = "repair:" + "a" * 64
        repair_close_id = "b" * 64
        attempt_record_id = "d" * 64
        records = {
            stem + "-repair-permit": SimpleNamespace(
                authority_sequence=100,
                record_id=stem + "-repair-permit",
                status="success",
                payload={"event_kind": "permit_issued", "result": {}},
            ),
            stem + "-open-repair": SimpleNamespace(
                authority_sequence=101,
                record_id=stem + "-open-repair",
                status="success",
                payload={
                    "event_kind": "repair_opened",
                    "result": {"repair_id": repair_id},
                },
            ),
            stem + "-close-repair": SimpleNamespace(
                authority_sequence=103,
                record_id=stem + "-close-repair",
                status="success",
                payload={
                    "event_kind": "repair_closed",
                    "result": {
                        "repair_close_record_id": repair_close_id,
                        "repair_id": repair_id,
                    },
                },
            ),
            repair_id: SimpleNamespace(
                payload={
                    "episode": 1,
                    "predecessor_repair_close_record_id": None,
                },
            ),
            repair_close_id: SimpleNamespace(
                status="repaired",
                payload={"repair_id": repair_id},
            ),
        }
        failed = SimpleNamespace(
            authority_sequence=102,
            record_id=stem + "-repair-attempt-001",
            status="success",
            payload={
                "event_kind": "repair_attempt_failed",
                "result": {
                    "attempt_record_id": attempt_record_id,
                    "repair_id": repair_id,
                },
            },
        )
        attempt_projection = SimpleNamespace(
            event_sequence=1,
            event_stream=f"repair-attempt:{repair_id}",
            kind="repair-attempt",
            payload={"repair_id": repair_id},
            record_id=attempt_record_id,
            status="failed",
        )
        projected = Mock()
        projected.get.side_effect = lambda _kind, record_id: records.get(
            record_id
        )
        projected.records_by_kind_prefix.return_value = (failed,)
        projected.records_by_subject_status.return_value = (
            attempt_projection,
        )

        steps = _member_repair_chain_complete(
            _snapshot_writer(projected),
            design,
            member,
        )

        self.assertEqual(
            [step.event_kind for step in steps],
            [
                "permit_issued",
                "repair_opened",
                "repair_attempt_failed",
                "repair_closed",
                "job_repaired_execution_resumed",
            ],
        )

        records.pop(stem + "-close-repair")
        unrecovered_close_id = "c" * 64
        records[stem + "-conclude-repair"] = SimpleNamespace(
            authority_sequence=102,
            record_id=stem + "-conclude-repair",
            status="success",
            payload={
                "event_kind": "repair_concluded_unrecovered",
                "result": {
                    "repair_close_record_id": unrecovered_close_id,
                    "repair_id": repair_id,
                },
            },
        )
        records[unrecovered_close_id] = SimpleNamespace(
            status="unrecovered",
            payload={"repair_id": repair_id},
        )
        projected.records_by_kind_prefix.return_value = ()
        projected.records_by_subject_status.return_value = ()
        concluded_steps = _member_repair_chain_complete(
            _snapshot_writer(projected),
            design,
            member,
        )
        self.assertEqual(
            concluded_steps[-1].event_kind,
            "repair_concluded_unrecovered",
        )

    def test_multiple_repair_episodes_are_contiguous_and_all_resumed(
        self,
    ) -> None:
        design = self._design()
        member = design.members[0]
        stem = design.spec.operation_prefix + member.label
        repair_one = "repair:" + "1" * 64
        repair_two = "repair:" + "2" * 64
        close_one = "3" * 64
        close_two = "4" * 64
        attempt_two = "5" * 64
        episode_two = stem + "-repair-episode-002"

        def operation(
            record_id: str,
            sequence: int,
            event_kind: str,
            result: dict[str, str],
        ) -> SimpleNamespace:
            return SimpleNamespace(
                authority_sequence=sequence,
                record_id=record_id,
                status="success",
                payload={"event_kind": event_kind, "result": result},
            )

        operations = {
            stem + "-repair-permit": operation(
                stem + "-repair-permit", 100, "permit_issued", {}
            ),
            stem + "-open-repair": operation(
                stem + "-open-repair",
                101,
                "repair_opened",
                {"repair_id": repair_one},
            ),
            stem + "-close-repair": operation(
                stem + "-close-repair",
                102,
                "repair_closed",
                {
                    "repair_close_record_id": close_one,
                    "repair_id": repair_one,
                },
            ),
            stem + "-resume-repaired-job": operation(
                stem + "-resume-repaired-job",
                103,
                "job_repaired_execution_resumed",
                {"repair_close_record_id": close_one},
            ),
            episode_two + "-permit": operation(
                episode_two + "-permit", 104, "permit_issued", {}
            ),
            episode_two + "-open": operation(
                episode_two + "-open",
                105,
                "repair_opened",
                {"repair_id": repair_two},
            ),
            episode_two + "-attempt-001": operation(
                episode_two + "-attempt-001",
                106,
                "repair_attempt_failed",
                {
                    "attempt_record_id": attempt_two,
                    "repair_id": repair_two,
                },
            ),
            episode_two + "-close": operation(
                episode_two + "-close",
                107,
                "repair_closed",
                {
                    "repair_close_record_id": close_two,
                    "repair_id": repair_two,
                },
            ),
        }
        projections = {
            repair_one: SimpleNamespace(
                payload={
                    "episode": 1,
                    "predecessor_repair_close_record_id": None,
                }
            ),
            repair_two: SimpleNamespace(
                payload={
                    "episode": 2,
                    "predecessor_repair_close_record_id": close_one,
                }
            ),
            close_one: SimpleNamespace(
                status="repaired", payload={"repair_id": repair_one}
            ),
            close_two: SimpleNamespace(
                status="repaired", payload={"repair_id": repair_two}
            ),
        }
        projected = Mock()
        projected.get.side_effect = lambda _kind, record_id: (
            operations.get(record_id) or projections.get(record_id)
        )
        projected.records_by_kind_prefix.return_value = tuple(
            operations.values()
        )
        projected.records_by_subject_status.side_effect = (
            lambda subject, _status: (
                (
                    SimpleNamespace(
                        event_sequence=1,
                        event_stream=f"repair-attempt:{repair_two}",
                        kind="repair-attempt",
                        payload={"repair_id": repair_two},
                        record_id=attempt_two,
                        status="failed",
                    ),
                )
                if subject == f"Repair:{repair_two}"
                else ()
            )
        )

        steps = _member_repair_chain_complete(
            _snapshot_writer(projected),
            design,
            member,
        )

        self.assertEqual(
            [step.event_kind for step in steps],
            [
                "permit_issued",
                "repair_opened",
                "repair_closed",
                "job_repaired_execution_resumed",
                "permit_issued",
                "repair_opened",
                "repair_attempt_failed",
                "repair_closed",
                "job_repaired_execution_resumed",
            ],
        )
        self.assertEqual(steps[-1].operation_id, episode_two + "-resume")

        operations.pop(stem + "-resume-repaired-job")
        projected.records_by_kind_prefix.return_value = tuple(
            operations.values()
        )
        with self.assertRaisesRegex(RuntimeError, "omits engine re-entry"):
            _member_repair_chain_complete(
                _snapshot_writer(projected),
                design,
                member,
            )

    def test_family_repair_lookup_shares_one_authoritative_prefix_query(
        self,
    ) -> None:
        projected = Mock()
        projected.get.return_value = None
        projected.records_by_kind_prefix.return_value = ()
        design = self._design()

        chains = _all_member_repair_chains(
            _snapshot_writer(projected),
            design,
        )

        self.assertEqual(chains, {member.ordinal: () for member in design.members})
        projected.records_by_kind_prefix.assert_called_once_with(
            "operation",
            design.spec.operation_prefix,
        )
        projected.records_by_kind.assert_not_called()

    def test_runnable_replay_context_reads_use_authenticated_snapshots(
        self,
    ) -> None:
        root = Path(__file__).resolve().parents[2]
        targets = {
            "scripts/run_composite_routed_replay.py": (
                "historical_context_count"
            ),
            "scripts/run_stu0032_distribution_asymmetry_replay.py": (
                "require_historical_context"
            ),
            "scripts/run_stu0048_drawdown_replay.py": (
                "require_historical_context"
            ),
            "scripts/run_stu0051_volatility_duration_replay.py": (
                "require_historical_context"
            ),
        }
        for relative, function_name in targets.items():
            with self.subTest(path=relative):
                tree = ast.parse((root / relative).read_text(encoding="ascii"))
                functions = [
                    node
                    for node in tree.body
                    if isinstance(node, ast.FunctionDef)
                    and node.name == function_name
                ]
                self.assertEqual(len(functions), 1)
                calls = [
                    node.func
                    for node in ast.walk(functions[0])
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                ]
                self.assertTrue(
                    any(
                        call.attr == "open_stable_index"
                        and isinstance(call.value, ast.Name)
                        and call.value.id == "writer"
                        for call in calls
                    )
                )
                self.assertFalse(
                    any(call.attr == "open_read_only" for call in calls)
                )
                self.assertFalse(
                    any(
                        isinstance(node, ast.Attribute)
                        and node.attr == "index_path"
                        for node in ast.walk(functions[0])
                    )
                )


if __name__ == "__main__":
    unittest.main()
