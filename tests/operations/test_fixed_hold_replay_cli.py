from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import axiom_rift.operations.fixed_hold_replay_cli as cli


class FixedHoldReplayCliTests(unittest.TestCase):
    def _run(self, argv: list[str], *, study_id: str | None = None):
        return cli.run_fixed_hold_replay_command(
            repository_root=Path.cwd(),
            design_builder=lambda _writer: "design",
            job_runner=Mock(name="job_runner"),
            job_implementation_materializer=Mock(name="materializer"),
            study_id=study_id,
            argv=argv,
        )

    def test_invalid_diagnose_fails_before_writer_or_registry(self) -> None:
        with (
            patch.object(cli, "EvidenceValidatorRegistry") as registry,
            patch.object(cli, "StateWriter") as writer,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "requires exact Study-close event and revision",
            ):
                self._run(["--stage", "diagnose"])
        registry.assert_not_called()
        writer.assert_not_called()

    def test_read_only_plan_uses_an_empty_registry(self) -> None:
        registry_instance = object()
        writer_instance = object()
        with (
            patch.object(
                cli,
                "EvidenceValidatorRegistry",
                return_value=registry_instance,
            ) as registry,
            patch.object(
                cli,
                "StateWriter",
                return_value=writer_instance,
            ) as writer,
            patch.object(cli, "require_stable_head"),
            patch.object(
                cli,
                "read_only_summary",
                return_value={"mode": "read_only_plan"},
            ),
        ):
            result = self._run([])
        registry.assert_called_once_with(())
        writer.assert_called_once_with(
            Path.cwd().resolve(),
            validation_registry=registry_instance,
        )
        self.assertEqual(result, {"mode": "read_only_plan"})

    def test_closed_study_plan_returns_canonical_handoff_without_design(self) -> None:
        registry_instance = object()
        index = Mock()
        index.get.return_value = Mock(
            record_id="STU-0114",
            subject="Study:STU-0114",
            payload={
                "completion_record_id": "completion-1",
                "outcome": "preserved",
                "study_id": "STU-0114",
            },
        )
        control = {
            "next_action": {
                "kind": "portfolio_decision",
                "portfolio_snapshot_id": "portfolio-1",
            },
            "revision": 5452,
            "scientific": {"active_study": None},
        }
        stable = Mock()
        stable.__enter__ = Mock(return_value=(control, index))
        stable.__exit__ = Mock(return_value=False)
        writer_instance = Mock()
        writer_instance.open_stable_index.return_value = stable
        design_builder = Mock(name="design_builder")
        with (
            patch.object(
                cli,
                "EvidenceValidatorRegistry",
                return_value=registry_instance,
            ),
            patch.object(cli, "StateWriter", return_value=writer_instance),
            patch.object(cli, "require_stable_head"),
        ):
            result = cli.run_fixed_hold_replay_command(
                repository_root=Path.cwd(),
                design_builder=design_builder,
                job_runner=Mock(name="job_runner"),
                job_implementation_materializer=Mock(name="materializer"),
                study_id="STU-0114",
                argv=[],
            )
        design_builder.assert_not_called()
        self.assertEqual(result["mode"], "completed_study_handoff")
        self.assertEqual(result["next_action"], control["next_action"])
        self.assertEqual(result["state_revision"], 5452)

    def test_closed_study_rejects_another_execution_stage_without_design(
        self,
    ) -> None:
        design_builder = Mock(name="design_builder")
        with (
            patch.object(cli, "EvidenceValidatorRegistry"),
            patch.object(cli, "StateWriter", return_value=Mock()),
            patch.object(cli, "require_stable_head"),
            patch.object(
                cli,
                "_completed_study_handoff",
                return_value={"mode": "completed_study_handoff"},
            ),
            self.assertRaisesRegex(RuntimeError, "rejects another execution"),
        ):
            cli.run_fixed_hold_replay_command(
                repository_root=Path.cwd(),
                design_builder=design_builder,
                job_runner=Mock(name="job_runner"),
                job_implementation_materializer=Mock(name="materializer"),
                study_id="STU-0114",
                argv=["--stage", "study-close"],
            )
        design_builder.assert_not_called()

    def test_closed_study_pending_diagnosis_runs_only_diagnose_stage(
        self,
    ) -> None:
        writer_instance = Mock()
        design = object()
        design_builder = Mock(return_value=design)
        with (
            patch.object(cli, "EvidenceValidatorRegistry"),
            patch.object(cli, "StateWriter", return_value=writer_instance),
            patch.object(cli, "require_stable_head"),
            patch.object(
                cli,
                "_completed_study_handoff",
                return_value={"mode": "study_close_pending_diagnosis"},
            ),
            patch.object(
                cli,
                "run_diagnose_stage",
                return_value={"mode": "diagnose"},
            ) as diagnose,
        ):
            result = cli.run_fixed_hold_replay_command(
                repository_root=Path.cwd(),
                design_builder=design_builder,
                job_runner=Mock(name="job_runner"),
                job_implementation_materializer=Mock(name="materializer"),
                study_id="STU-0115",
                argv=[
                    "--stage",
                    "diagnose",
                    "--study-close-event-id",
                    "a" * 64,
                    "--study-close-revision",
                    "5486",
                ],
            )
        design_builder.assert_called_once_with(writer_instance)
        diagnose.assert_called_once()
        self.assertIs(diagnose.call_args.kwargs["design"], design)
        self.assertEqual(result, {"mode": "diagnose"})

    def test_diagnosed_closed_study_rejects_duplicate_diagnosis(self) -> None:
        design_builder = Mock(name="design_builder")
        with (
            patch.object(cli, "EvidenceValidatorRegistry"),
            patch.object(cli, "StateWriter", return_value=Mock()),
            patch.object(cli, "require_stable_head"),
            patch.object(
                cli,
                "_completed_study_handoff",
                return_value={"mode": "completed_study_handoff"},
            ),
            self.assertRaisesRegex(RuntimeError, "no pending diagnosis"),
        ):
            cli.run_fixed_hold_replay_command(
                repository_root=Path.cwd(),
                design_builder=design_builder,
                job_runner=Mock(name="job_runner"),
                job_implementation_materializer=Mock(name="materializer"),
                study_id="STU-0115",
                argv=[
                    "--stage",
                    "diagnose",
                    "--study-close-event-id",
                    "a" * 64,
                    "--study-close-revision",
                    "5486",
                ],
            )
        design_builder.assert_not_called()

    def test_diagnose_uses_no_validator_or_permit_key(self) -> None:
        registry_instance = object()
        writer_instance = object()
        with (
            patch.object(
                cli,
                "EvidenceValidatorRegistry",
                return_value=registry_instance,
            ) as registry,
            patch.object(
                cli,
                "StateWriter",
                return_value=writer_instance,
            ),
            patch.object(cli, "require_stable_head"),
            patch.object(cli, "PermitKeyStore") as key_store,
            patch.object(
                cli,
                "run_diagnose_stage",
                return_value={"mode": "diagnose"},
            ) as diagnose,
        ):
            result = self._run(
                [
                    "--stage",
                    "diagnose",
                    "--study-close-event-id",
                    "a" * 64,
                    "--study-close-revision",
                    "1",
                ]
            )
        registry.assert_called_once_with(())
        key_store.assert_not_called()
        diagnose.assert_called_once()
        self.assertEqual(result, {"mode": "diagnose"})

    def test_study_close_registers_only_scientific_validation(self) -> None:
        scientific = object()
        registry_instance = object()
        writer_instance = Mock()
        permit_authority = object()
        key_store_instance = Mock()
        key_store_instance.load_or_create.return_value = b"key"
        with (
            patch.object(
                cli,
                "ScientificAdjudicationValidatorV2",
                return_value=scientific,
            ),
            patch.object(
                cli,
                "EvidenceValidatorRegistry",
                return_value=registry_instance,
            ) as registry,
            patch.object(
                cli,
                "StateWriter",
                return_value=writer_instance,
            ),
            patch.object(cli, "require_stable_head"),
            patch.object(
                cli,
                "PermitKeyStore",
                return_value=key_store_instance,
            ),
            patch.object(
                cli,
                "PermitAuthority",
                return_value=permit_authority,
            ),
            patch.object(
                cli,
                "run_study_close_stage",
                return_value={"mode": "study_close"},
            ) as study_close,
        ):
            result = self._run(["--stage", "study-close"])
        registry.assert_called_once_with((scientific,))
        self.assertIs(writer_instance.permit_authority, permit_authority)
        key_store_instance.load_or_create.assert_called_once_with()
        study_close.assert_called_once()
        self.assertEqual(result, {"mode": "study_close"})


if __name__ == "__main__":
    unittest.main()
