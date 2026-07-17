from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.operations.permits import (
    PermitAuthority,
    PermitKind,
    SubjectKind,
)
from axiom_rift.operations.replay_job_implementation_preflight import (
    ReplayJobImplementationPreflightError,
    ReplayJobImplementationPreflightRequest,
)
from axiom_rift.operations.validation import EvidenceValidatorRegistry
from axiom_rift.operations.writer import StateWriter, TransitionError
from axiom_rift.research.chassis import ControlledStudyChassis
from axiom_rift.research.portfolio import (
    DecisionOption,
    PortfolioAction,
    PortfolioDecision,
    PortfolioSnapshot,
)
from axiom_rift.research.semantic_question import (
    SemanticQuestionCore,
    SemanticQuestionLineageProposal,
    SemanticQuestionRelation,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex
from tests.operations.fixture_validators import ComponentParityFixtureValidator
from tests.operations.test_writer import (
    FIXED_EXPIRY,
    FIXED_NOW,
    FIXTURE_DELIVERY_CAPABILITY,
    OBSERVED_MATERIAL_ID,
    REPO_ROOT,
    PortfolioAxis as fixture_portfolio_axis,
    batch_spec,
    exhaustion_standard,
    initiative_objective,
    mission_goal,
    quant_team_review_for_current_action,
    record_fixture_research_intake,
    scientific_executable_spec,
    study_question,
)


MISSION_ID = "MIS-REPLACEMENT-WRITER-GATE"
INITIATIVE_ID = "INI-REPLACEMENT-WRITER-GATE"
STUDY_ID = "STU-REPLACEMENT-WRITER-GATE"
OBLIGATION_ID = "historical-replay-obligation:" + "2" * 64
TRIGGER_ID = "job-implementation-preflight:" + "4" * 64
EQUIVALENCE_HASH = "5" * 64
SURFACE_HASH = "6" * 64


class ReplayReplacementWriterGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.writer = StateWriter(
            Path(self.temporary.name),
            permit_authority=PermitAuthority(b"r" * 32),
            clock=lambda: FIXED_NOW,
            study_close_guard_capability=FIXTURE_DELIVERY_CAPABILITY,
            foundation_root=REPO_ROOT,
            validation_registry=EvidenceValidatorRegistry(
                (ComponentParityFixtureValidator(),)
            ),
        )
        self.writer.initialize_ready()
        self.writer.open_mission(
            mission_id=MISSION_ID,
            goal=mission_goal("replacement Writer gate"),
            operation_id="replacement-gate-mission",
        )
        self.intake = record_fixture_research_intake(
            self.writer,
            mission_id=MISSION_ID,
            operation_id="replacement-gate-intake",
        )
        self.writer.open_initiative(
            initiative_id=INITIATIVE_ID,
            objective=initiative_objective("replacement Writer gate"),
            operation_id="replacement-gate-initiative",
        )
        self.axes = tuple(
            fixture_portfolio_axis(
                axis_id=f"replacement-writer-axis-{letter}",
                causal_question=(
                    f"Does replacement Writer axis {letter} identify the bottleneck?"
                ),
                mechanism_family=f"replacement-writer-family-{letter}",
            )
            for letter in ("a", "b", "c")
        )
        self.snapshot = PortfolioSnapshot(
            mission_id=MISSION_ID,
            axes=self.axes,
            opportunity_cost_basis=(
                "bind one replacement implementation without changing its science"
            ),
            research_intake_id=self.intake.identity,
            exhaustion_standard=exhaustion_standard(),
        )
        self.writer.record_portfolio_snapshot(
            snapshot=self.snapshot,
            operation_id="replacement-gate-snapshot",
        )

    def test_decision_to_study_rejects_replacement_drift_before_study_write(
        self,
    ) -> None:
        axis = self.axes[0]
        replacement_baseline = scientific_executable_spec(
            "replacement-writer-gate",
            architecture_variant="alternate",
        )
        replacement_member = scientific_executable_spec(
            "replacement-writer-gate-member",
            architecture_variant="alternate",
        )
        options = (
            DecisionOption(
                option_id="execute-replacement",
                action=PortfolioAction.SYNTHESIZE,
                target_id=axis.axis_id,
                expected_information_value="positive",
                opportunity_cost="one bounded replacement Batch",
            ),
            DecisionOption(
                option_id="retain-alternative",
                action=PortfolioAction.ROTATE,
                target_id=self.axes[1].axis_id,
                expected_information_value="positive",
                opportunity_cost="deferred",
                omission_reason="the exact replacement is tested first",
            ),
        )
        decision = PortfolioDecision(
            decision_id="DEC-REPLACEMENT-WRITER-GATE",
            chosen_option_id="execute-replacement",
            options=options,
            rationale="rerun the same science through the accepted replacement",
            commitment_batches=1,
            quant_team_review=quant_team_review_for_current_action(
                self.writer,
                options=options,
                chosen_option_id="execute-replacement",
            ),
            baseline_executable=replacement_baseline,
            replay_obligation_ids=(OBLIGATION_ID,),
        )
        assert decision.architecture_chassis is not None
        assert axis.architecture_chassis is not None
        self.assertNotEqual(
            decision.architecture_chassis.identity,
            axis.architecture_chassis.identity,
        )
        controlled_chassis = ControlledStudyChassis(
            baseline_executable=replacement_baseline,
            changed_domains=axis.changed_domains,
            controlled_domains=axis.controlled_domains,
            architecture=decision.architecture_chassis,
        )
        question = {
            **study_question("replacement Writer gate"),
            "causal_question": axis.causal_question,
        }
        proposal = {"mechanism": axis.mechanism_family}
        core = SemanticQuestionCore.from_question_manifest(question)
        lineage = SemanticQuestionLineageProposal(
            predecessor_study_id="STU-REPLACEMENT-WRITER-PREDECESSOR",
            successor_study_id=STUDY_ID,
            predecessor_core_id=core.identity,
            successor_core_id=core.identity,
            relation=SemanticQuestionRelation.ENGINEERING_REENTRY,
            rationale="replace implementation bytes while preserving the question",
            basis_record_ids=(f"job-implementation-preflight:{TRIGGER_ID}",),
        )
        request = ReplayJobImplementationPreflightRequest(
            mission_id=MISSION_ID,
            protocol_id="python.tests.replacement_writer_gate.v1",
            callable_identity="python:tests.replacement_writer_gate",
            implementation_identity="1" * 64,
            executables=(replacement_member,),
            scientific_bindings=({"validation_plan_hash": "3" * 64},),
            replay_obligation_ids=(OBLIGATION_ID,),
        )
        study_hash = self.writer.study_input_hash(
            question=question,
            material_identity=OBSERVED_MATERIAL_ID,
            semantic_proposal=proposal,
            semantic_question_lineage=lineage,
            controlled_chassis=controlled_chassis,
            portfolio_axis_id=axis.axis_id,
            portfolio_axis_identity=axis.identity,
            portfolio_decision_id=decision.identity,
        )
        batch = batch_spec(
            batch_id="BAT-REPLACEMENT-WRITER-GATE",
            study_id=STUDY_ID,
            study_hash=study_hash,
        )
        axis_payload = next(
            item
            for item in self.snapshot.to_identity_payload()["axes"]
            if item["axis_id"] == axis.axis_id
        )
        prospective_study = {
            "changed_domains": axis_payload["changed_domains"],
            "controlled_chassis": controlled_chassis.to_identity_payload(),
            "controlled_domains": axis_payload["controlled_domains"],
            "material_identity": OBSERVED_MATERIAL_ID,
            "mechanism_family": axis.mechanism_family,
            "mission_id": MISSION_ID,
            "portfolio_action": PortfolioAction.SYNTHESIZE.value,
            "primary_research_layer": axis.primary_research_layer.value,
            "question": question,
            "replay_obligation_ids": [OBLIGATION_ID],
            "semantic_proposal": proposal,
            "semantic_question_core_id": core.identity,
        }
        trigger = IndexRecord(
            kind="job-implementation-preflight",
            record_id=TRIGGER_ID,
            subject=f"Mission:{MISSION_ID}",
            status="accepted",
            fingerprint="4" * 64,
            payload={
                "mission_id": MISSION_ID,
                "outcome": "accepted",
                "schema": "replay_job_implementation_preflight.v1",
            },
        )

        def require_study_semantics(
            *,
            accepted_payload,
            study_payload,
        ) -> str:
            if not accepted_payload:
                raise ReplayJobImplementationPreflightError(
                    "accepted replacement trigger is stale"
                )
            if canonical_bytes(study_payload) != canonical_bytes(
                prospective_study
            ):
                raise ReplayJobImplementationPreflightError(
                    "prospective replacement Study drifted"
                )
            return EQUIVALENCE_HASH

        def derive_surface(
            active_request,
            *,
            study_payload,
            batch_payload,
            artifact_reader,
            **_kwargs,
        ):
            del artifact_reader
            return {
                "batch": batch_payload,
                "request_identity": active_request.identity,
                "schema": "replacement_writer_gate_surface.v1",
                "study": study_payload,
            }

        current_preflight = SimpleNamespace(
            accepted=True,
            failure_detail=None,
            reason_code=None,
            source_closure_authority={"schema": "fixture_source_closure.v1"},
        )

        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "axiom_rift.operations.research_protocol_projection."
                    "require_current_research_protocol_activation",
                    return_value=SimpleNamespace(
                        record_id="research-protocol-activation:" + "9" * 64
                    ),
                )
            )
            trigger_resolver = stack.enter_context(
                patch.object(
                    self.writer,
                    "_current_accepted_replay_replacement_preflight",
                    return_value=trigger,
                )
            )
            stack.enter_context(
                patch(
                    "axiom_rift.operations.replay_projection."
                    "validate_decision_selection",
                    return_value=None,
                )
            )
            stack.enter_context(
                patch(
                    "axiom_rift.operations.replay_projection."
                    "validate_replay_review_basis",
                    return_value=None,
                )
            )
            stack.enter_context(
                patch(
                    "axiom_rift.operations.replay_projection.require_study_pending",
                    return_value=(OBLIGATION_ID,),
                )
            )
            stack.enter_context(
                patch(
                    "axiom_rift.operations.replay_job_implementation_preflight."
                    "derive_replay_job_scientific_surface",
                    side_effect=derive_surface,
                )
            )
            stack.enter_context(
                patch(
                    "axiom_rift.operations.replay_job_implementation_preflight."
                    "evaluate_replay_job_implementation_preflight",
                    return_value=current_preflight,
                )
            )
            stack.enter_context(
                patch(
                    "axiom_rift.operations.replay_job_implementation_preflight."
                    "replay_job_scientific_surface_hash",
                    return_value=SURFACE_HASH,
                )
            )
            stack.enter_context(
                patch(
                    "axiom_rift.operations.replay_job_implementation_preflight."
                    "require_active_replay_job_replacement_binding",
                    return_value=None,
                )
            )
            stack.enter_context(
                patch(
                    "axiom_rift.operations.replay_job_implementation_preflight."
                    "require_replacement_replay_baseline_semantics",
                    return_value=EQUIVALENCE_HASH,
                )
            )
            stack.enter_context(
                patch(
                    "axiom_rift.operations.replay_job_implementation_preflight."
                    "require_replacement_replay_study_semantics",
                    side_effect=require_study_semantics,
                )
            )

            recorded = self.writer.record_portfolio_decision(
                decision=decision,
                operation_id="replacement-gate-decision",
                replacement_replay_batch_spec=batch,
                replacement_replay_implementation_request=request,
                replacement_replay_study_payload=prospective_study,
                replacement_semantic_question_lineage=lineage,
            )
            self.assertEqual(recorded.result["decision_id"], decision.identity)

            with LocalIndex(self.writer.index_path) as index:
                durable_decision = index.get(
                    "portfolio-decision",
                    decision.identity,
                )
                self.assertIsNotNone(durable_decision)
                assert durable_decision is not None
                self.assertEqual(
                    durable_decision.payload[
                        "replacement_architecture_equivalence"
                    ]["accepted_replacement_preflight_id"],
                    TRIGGER_ID,
                )
                equivalence = durable_decision.payload[
                    "replacement_architecture_equivalence"
                ]
                self.assertEqual(
                    equivalence["replacement_baseline_executable_id"],
                    replacement_baseline.identity,
                )
                self.assertEqual(
                    equivalence["replacement_executable_ids"],
                    [replacement_member.identity],
                )
                self.assertNotIn(
                    replacement_baseline.identity,
                    equivalence["replacement_executable_ids"],
                )
                self.assertIsNone(index.get("study-open", STUDY_ID))
                self.assertEqual(len(index.records_by_kind("trial")), 0)

            def issue_study_permit(
                tag: str,
                *,
                active_proposal=proposal,
                active_lineage=lineage,
            ):
                active_hash = self.writer.study_input_hash(
                    question=question,
                    material_identity=OBSERVED_MATERIAL_ID,
                    semantic_proposal=active_proposal,
                    semantic_question_lineage=active_lineage,
                    controlled_chassis=controlled_chassis,
                    portfolio_axis_id=axis.axis_id,
                    portfolio_axis_identity=axis.identity,
                    portfolio_decision_id=decision.identity,
                )
                return self.writer.issue_permit(
                    kind=PermitKind.STUDY,
                    subject_kind=SubjectKind.INITIATIVE,
                    subject_id=INITIATIVE_ID,
                    input_hash=active_hash,
                    actions=("open_study",),
                    scope=(
                        "study",
                        f"decision:{decision.identity}",
                        f"axis:{axis.identity}",
                        f"baseline:{replacement_baseline.identity}",
                        f"chassis:{decision.architecture_chassis.identity}",
                        f"snapshot:{self.snapshot.identity}",
                    ),
                    expires_at_utc=FIXED_EXPIRY,
                    one_shot=True,
                    operation_id=f"replacement-gate-{tag}-permit",
                )

            valid_permit = issue_study_permit("valid")

            def attempt_open(
                tag: str,
                *,
                active_proposal=proposal,
                active_request=request,
                active_batch=batch,
                active_lineage=lineage,
                permit=valid_permit,
            ):
                return self.writer.open_study(
                    study_id=STUDY_ID,
                    question=question,
                    material_identity=OBSERVED_MATERIAL_ID,
                    material_display_name="foundation observed material",
                    semantic_proposal=active_proposal,
                    semantic_question_lineage=active_lineage,
                    controlled_chassis=controlled_chassis,
                    portfolio_axis_id=axis.axis_id,
                    portfolio_axis_identity=axis.identity,
                    portfolio_decision_id=decision.identity,
                    permit=permit,
                    operation_id=f"replacement-gate-{tag}-open",
                    replay_implementation_request=active_request,
                    replay_batch_spec=active_batch,
                )

            def assert_no_study_or_trial() -> None:
                with LocalIndex(self.writer.index_path) as index:
                    self.assertIsNone(index.get("study-open", STUDY_ID))
                    self.assertEqual(len(index.records_by_kind("trial")), 0)

            trigger_resolver.return_value = None
            with self.assertRaisesRegex(
                TransitionError,
                "exact accepted scientific equivalence",
            ):
                attempt_open("stale-trigger")
            assert_no_study_or_trial()
            trigger_resolver.return_value = trigger

            tampered_proposal = {
                **proposal,
                "tampered_surface": "must not cross the Decision boundary",
            }
            tampered_study_permit = issue_study_permit(
                "tampered-study",
                active_proposal=tampered_proposal,
            )
            with self.assertRaisesRegex(
                TransitionError,
                "exact accepted scientific equivalence",
            ):
                attempt_open(
                    "tampered-study",
                    active_proposal=tampered_proposal,
                    permit=tampered_study_permit,
                )
            assert_no_study_or_trial()

            tampered_request = ReplayJobImplementationPreflightRequest(
                mission_id=request.mission_id,
                protocol_id=request.protocol_id,
                callable_identity=request.callable_identity,
                implementation_identity="7" * 64,
                executables=request.executables,
                scientific_bindings=request.scientific_binding_values(),
                replay_obligation_ids=request.replay_obligation_ids,
            )
            with self.assertRaisesRegex(
                TransitionError,
                "accepted Decision equivalence",
            ):
                attempt_open(
                    "tampered-request",
                    active_request=tampered_request,
                )
            assert_no_study_or_trial()

            tampered_batch = batch_spec(
                batch_id="BAT-REPLACEMENT-WRITER-GATE-TAMPERED",
                study_id=STUDY_ID,
                study_hash=study_hash,
                max_compute_seconds=batch.max_compute_seconds + 1,
            )
            with self.assertRaisesRegex(
                TransitionError,
                "accepted Decision equivalence",
            ):
                attempt_open(
                    "tampered-batch",
                    active_batch=tampered_batch,
                )
            assert_no_study_or_trial()

            tampered_lineage = replace(
                lineage,
                rationale="tampered engineering reentry lineage",
            )
            tampered_lineage_permit = issue_study_permit(
                "tampered-lineage",
                active_lineage=tampered_lineage,
            )
            with self.assertRaisesRegex(
                TransitionError,
                "accepted Decision equivalence",
            ):
                attempt_open(
                    "tampered-lineage",
                    active_lineage=tampered_lineage,
                    permit=tampered_lineage_permit,
                )
            assert_no_study_or_trial()

            opened = attempt_open("valid")
            self.assertEqual(opened.result["study_id"], STUDY_ID)
            with LocalIndex(self.writer.index_path) as index:
                self.assertIsNotNone(index.get("study-open", STUDY_ID))
                admissions = index.records_by_kind(
                    "replay-implementation-admission"
                )
                self.assertEqual(len(admissions), 1)
                self.assertEqual(
                    admissions[0].payload[
                        "accepted_replacement_preflight_id"
                    ],
                    TRIGGER_ID,
                )
                self.assertEqual(len(index.records_by_kind("trial")), 0)


if __name__ == "__main__":
    unittest.main()
