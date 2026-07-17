from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import axiom_rift.operations.fixed_hold_replay_cli as cli


class FixedHoldReplayCliTests(unittest.TestCase):
    def _run(self, argv: list[str]):
        return cli.run_fixed_hold_replay_command(
            repository_root=Path.cwd(),
            design_builder=lambda _writer: "design",
            job_runner=Mock(name="job_runner"),
            job_implementation_materializer=Mock(name="materializer"),
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
