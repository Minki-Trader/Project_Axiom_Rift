from __future__ import annotations

import ast
import inspect
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from axiom_rift.operations.writer import (
    RecoveryRequired as WriterRecoveryRequired,
    StateWriter,
    TransitionError as WriterTransitionError,
)
from axiom_rift.operations.writer_job_admission import JobAdmissionWriterMixin
from axiom_rift.operations.writer_job_execution import JobExecutionWriterMixin
from axiom_rift.operations.writer_historical_replay import (
    HistoricalReplayWriterMixin,
)
from axiom_rift.operations.writer_holdout import HoldoutWriterMixin
from axiom_rift.operations.writer_lifecycle import (
    BatchLifecycleWriterMixin,
    StudyCloseWriterMixin,
    StudyKpiProjectionWriterMixin,
    StudyLifecycleWriterMixin,
)
from axiom_rift.operations.writer_portfolio_decision import (
    PortfolioDecisionWriterMixin,
)
from axiom_rift.operations.writer_portfolio_withdrawal import (
    PortfolioWithdrawalWriterMixin,
)
from axiom_rift.operations.writer_repair import RepairWriterMixin
from axiom_rift.operations.writer_source_authority import (
    SourceAuthorityWriterMixin,
)
from axiom_rift.operations.writer_study_admission import (
    StudyAdmissionWriterMixin,
)
from axiom_rift.operations.writer_study_diagnosis import (
    StudyDiagnosisWriterMixin,
)
from axiom_rift.operations.writer_support import (
    RecoveryRequired,
    TransitionError,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_HASH = "a" * 64


class WriterEvidenceSnapshotBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.writer = StateWriter(
            Path(self.temporary.name),
            engineering_fixture=True,
            foundation_root=REPO_ROOT,
        )

    def test_writer_uses_only_public_evidence_snapshot_capabilities(self) -> None:
        tree = ast.parse(
            "\n".join(
                (
                    inspect.getsource(StateWriter),
                    inspect.getsource(HistoricalReplayWriterMixin),
                    inspect.getsource(HoldoutWriterMixin),
                    inspect.getsource(JobAdmissionWriterMixin),
                    inspect.getsource(JobExecutionWriterMixin),
                    inspect.getsource(RepairWriterMixin),
                    inspect.getsource(SourceAuthorityWriterMixin),
                    inspect.getsource(StudyAdmissionWriterMixin),
                    inspect.getsource(StudyDiagnosisWriterMixin),
                    inspect.getsource(BatchLifecycleWriterMixin),
                    inspect.getsource(StudyKpiProjectionWriterMixin),
                    inspect.getsource(StudyCloseWriterMixin),
                    inspect.getsource(StudyLifecycleWriterMixin),
                    inspect.getsource(PortfolioDecisionWriterMixin),
                    inspect.getsource(PortfolioWithdrawalWriterMixin),
                )
            )
        )
        private_root_reads = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr == "_root"
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "evidence"
        ]
        self.assertEqual(private_root_reads, [])

        for method_name in (
            "_derive_release_basis_locked",
            "resume_historical_replay_obligations",
            "_derive_runtime_job_evidence",
            "_derive_source_job_evidence",
            "_derive_scientific_job_evidence",
            "_derive_external_dependency_evidence",
            "_derive_component_parity_job_evidence",
            "register_future_development_material",
            "reveal_holdout_values",
            "resume_blocked_mission",
        ):
            with self.subTest(method_name=method_name):
                self.assertIn(
                    "self.evidence.read_verified(",
                    inspect.getsource(getattr(StateWriter, method_name)),
                )

        for method_name in (
            "_run_registered_validator",
            "_run_implementation_repair_semantic_equivalence",
            "resume_blocked_mission",
        ):
            with self.subTest(method_name=method_name):
                self.assertIn(
                    "self.evidence.verified_path(",
                    inspect.getsource(getattr(StateWriter, method_name)),
                )

    def test_batch_and_study_lifecycle_is_owned_by_the_focused_mixin(self) -> None:
        self.assertTrue(issubclass(StateWriter, StudyLifecycleWriterMixin))
        expected_owners = {
            "open_batch": BatchLifecycleWriterMixin,
            "review_study_continuation": BatchLifecycleWriterMixin,
            "close_study": StudyCloseWriterMixin,
            "rebuild_study_kpi_projection": StudyKpiProjectionWriterMixin,
        }
        for method_name, owner in expected_owners.items():
            with self.subTest(method_name=method_name):
                method = getattr(StateWriter, method_name)
                self.assertIs(method, getattr(owner, method_name))
                self.assertEqual(
                    method.__module__,
                    "axiom_rift.operations.writer_lifecycle",
                )
                self.assertNotIn(method_name, StateWriter.__dict__)

    def test_job_and_repair_domains_are_owned_by_focused_mixins(self) -> None:
        expected_owners = {
            "declare_job": JobAdmissionWriterMixin,
            "record_replay_job_implementation_preflight": (
                JobAdmissionWriterMixin
            ),
            "start_job": JobExecutionWriterMixin,
            "complete_job": JobExecutionWriterMixin,
            "judge_job_evidence": JobExecutionWriterMixin,
            "open_repair": RepairWriterMixin,
            "evaluate_repair_candidate": RepairWriterMixin,
            "close_repair": RepairWriterMixin,
        }
        for method_name, owner in expected_owners.items():
            with self.subTest(method_name=method_name):
                method = getattr(StateWriter, method_name)
                self.assertIs(method, getattr(owner, method_name))
                self.assertNotIn(method_name, StateWriter.__dict__)

    def test_holdout_domain_is_owned_by_the_focused_mixin(self) -> None:
        method_names = (
            "record_holdout_seal",
            "register_future_development_material",
            "consume_holdout_permit",
            "reveal_holdout_values",
            "record_holdout_evaluation",
            "dispose_revealed_holdout_engineering_gap",
            "_resolved_candidate_disposition_for_completion",
            "_candidate_authority_for_axis_bindings",
        )
        self.assertTrue(issubclass(StateWriter, HoldoutWriterMixin))
        for method_name in method_names:
            with self.subTest(method_name=method_name):
                self.assertIs(
                    inspect.getattr_static(StateWriter, method_name),
                    inspect.getattr_static(HoldoutWriterMixin, method_name),
                )
                self.assertNotIn(method_name, StateWriter.__dict__)
        self.assertNotIn("_commit", HoldoutWriterMixin.__dict__)
        self.assertNotIn(
            "axiom_rift.operations.writer",
            inspect.getsource(HoldoutWriterMixin),
        )

    def test_research_admission_and_history_are_owned_by_focused_mixins(
        self,
    ) -> None:
        expected_owners = {
            "record_historical_scientific_validity_invalidations": (
                HistoricalReplayWriterMixin
            ),
            "resume_historical_replay_obligations": (
                HistoricalReplayWriterMixin
            ),
            "record_historical_scientific_adjudications": (
                HistoricalReplayWriterMixin
            ),
            "record_source_eligibility": SourceAuthorityWriterMixin,
            "suspend_source_authority_from_audit": SourceAuthorityWriterMixin,
            "record_source_replacement_lineage": SourceAuthorityWriterMixin,
            "open_study": StudyAdmissionWriterMixin,
            "study_input_hash": StudyAdmissionWriterMixin,
            "study_chassis_combination_identity": StudyAdmissionWriterMixin,
            "record_study_diagnosis": StudyDiagnosisWriterMixin,
            "record_study_diagnosis_corrections": StudyDiagnosisWriterMixin,
            "record_architecture_review": StudyDiagnosisWriterMixin,
        }
        for method_name, owner in expected_owners.items():
            with self.subTest(method_name=method_name):
                self.assertIs(
                    inspect.getattr_static(StateWriter, method_name),
                    inspect.getattr_static(owner, method_name),
                )
                self.assertNotIn(method_name, StateWriter.__dict__)
        for owner in set(expected_owners.values()):
            self.assertNotIn("_commit", owner.__dict__)
            self.assertNotIn(
                "axiom_rift.operations.writer",
                inspect.getsource(owner),
            )

    def test_open_study_is_an_orchestrator_not_another_god_method(self) -> None:
        source_lines = inspect.getsource(
            StudyAdmissionWriterMixin.open_study
        ).splitlines()
        self.assertLess(len(source_lines), 350)
        for helper in (
            "_prepare_study_portfolio_plan",
            "_prepare_study_replay_admission",
            "_prepare_study_trial_context",
            "_build_study_open_record",
            "_build_study_semantic_records",
        ):
            with self.subTest(helper=helper):
                self.assertIn(helper, StudyAdmissionWriterMixin.__dict__)

    def test_portfolio_domains_are_owned_by_focused_mixins(self) -> None:
        expected_owners = {
            "_portfolio_decision_withdrawal": (
                PortfolioWithdrawalWriterMixin
            ),
            "_active_portfolio_decision": PortfolioWithdrawalWriterMixin,
            "record_portfolio_snapshot": PortfolioDecisionWriterMixin,
            "record_axis_reopen_authority": PortfolioDecisionWriterMixin,
            "record_portfolio_decision": PortfolioDecisionWriterMixin,
            "withdraw_pending_portfolio_decision": (
                PortfolioWithdrawalWriterMixin
            ),
            "withdraw_unbound_execution_plan_portfolio_decision": (
                PortfolioWithdrawalWriterMixin
            ),
            "withdraw_structurally_invalid_portfolio_decision": (
                PortfolioWithdrawalWriterMixin
            ),
        }
        for method_name, owner in expected_owners.items():
            with self.subTest(method_name=method_name):
                method = getattr(StateWriter, method_name)
                self.assertIs(method, getattr(owner, method_name))
                self.assertNotIn(method_name, StateWriter.__dict__)

        self.assertNotIn("_commit", PortfolioDecisionWriterMixin.__dict__)
        self.assertNotIn("_commit", PortfolioWithdrawalWriterMixin.__dict__)
        for owner in (
            PortfolioDecisionWriterMixin,
            PortfolioWithdrawalWriterMixin,
        ):
            self.assertNotIn(
                "axiom_rift.operations.writer",
                inspect.getsource(owner),
            )
        self.assertIs(
            inspect.getattr_static(
                PortfolioWithdrawalWriterMixin,
                "_portfolio_decision_withdrawal",
            ).__func__,
            PortfolioWithdrawalWriterMixin._portfolio_decision_withdrawal,
        )
        self.assertIs(
            inspect.getattr_static(
                PortfolioWithdrawalWriterMixin,
                "_active_portfolio_decision",
            ).__func__,
            PortfolioWithdrawalWriterMixin._active_portfolio_decision,
        )
        self.assertIs(WriterTransitionError, TransitionError)
        self.assertIs(WriterRecoveryRequired, RecoveryRequired)
        self.assertEqual(
            StateWriter._commit.__module__,
            "axiom_rift.operations.writer",
        )

    def test_holdout_reveal_propagates_verified_snapshot_error(self) -> None:
        expected = RuntimeError("verified snapshot failed")
        consumed = SimpleNamespace(
            reused=False,
            result={"artifact_sha256": ARTIFACT_HASH},
        )
        with (
            patch.object(
                self.writer,
                "consume_holdout_permit",
                return_value=consumed,
            ),
            patch.object(
                self.writer.evidence,
                "read_verified",
                side_effect=expected,
            ),
        ):
            with self.assertRaises(RuntimeError) as raised:
                self.writer.reveal_holdout_values(
                    permit=object(),  # type: ignore[arg-type]
                    executable_id="exe:fixture",
                    operation_id="reveal-fixture",
                )
        self.assertIs(raised.exception, expected)

    def test_holdout_reveal_returns_exact_verified_snapshot_bytes(self) -> None:
        payload = b"\x00exact-holdout-snapshot\xff"
        consumed = SimpleNamespace(
            reused=False,
            result={"artifact_sha256": ARTIFACT_HASH},
        )
        with (
            patch.object(
                self.writer,
                "consume_holdout_permit",
                return_value=consumed,
            ),
            patch.object(
                self.writer.evidence,
                "read_verified",
                return_value=payload,
            ) as read_verified,
        ):
            observed = self.writer.reveal_holdout_values(
                permit=object(),  # type: ignore[arg-type]
                executable_id="exe:fixture",
                operation_id="reveal-fixture",
            )
        self.assertIs(observed, payload)
        read_verified.assert_called_once_with(ARTIFACT_HASH)


if __name__ == "__main__":
    unittest.main()
