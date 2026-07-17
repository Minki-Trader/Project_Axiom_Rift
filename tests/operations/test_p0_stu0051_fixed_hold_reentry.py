from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


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

    def test_repair_operation_namespace_matches_the_strict_chain(self) -> None:
        spec = SimpleNamespace(operation_prefix=self.runner.OPERATION_PREFIX)
        member = SimpleNamespace(label="member-01")

        first = self.runner.fixed_hold_replay_repair_operation_ids(
            spec,
            member,
            episode=1,
        )
        stem = self.runner.OPERATION_PREFIX + "member-01"
        self.assertEqual(first.permit, stem + "-repair-permit")
        self.assertEqual(first.open, stem + "-open-repair")
        self.assertEqual(first.attempt_prefix, stem + "-repair-attempt-")
        self.assertEqual(first.close, stem + "-close-repair")
        self.assertEqual(first.resume, stem + "-resume-repaired-job")

        second = self.runner.fixed_hold_replay_repair_operation_ids(
            spec,
            member,
            episode=2,
        )
        self.assertEqual(
            second.by_role(),
            {
                "attempt_prefix": stem + "-repair-episode-002-attempt-",
                "close": stem + "-repair-episode-002-close",
                "conclude": stem + "-repair-episode-002-conclude",
                "open": stem + "-repair-episode-002-open",
                "permit": stem + "-repair-episode-002-permit",
                "resume": stem + "-repair-episode-002-resume",
            },
        )
        thousandth = self.runner.fixed_hold_replay_repair_operation_ids(
            spec,
            member,
            episode=1000,
        )
        self.assertEqual(
            thousandth.open,
            stem + "-repair-episode-1000-open",
        )

    def test_runner_pins_the_exact_repair_capability(self) -> None:
        from axiom_rift.operations.fixed_hold_repair_equivalence import (
            FIXED_HOLD_AUTHORITY_CORRECTION_VALIDATOR_ID,
        )

        self.assertEqual(
            self.runner.volatility_duration_fixed_hold_job_implementation_sha256(),
            self.runner.EXPECTED_REPAIR_NEW_IMPLEMENTATION_IDENTITY,
        )
        self.assertEqual(
            FIXED_HOLD_AUTHORITY_CORRECTION_VALIDATOR_ID,
            self.runner.EXPECTED_REPAIR_VALIDATOR_ID,
        )

    def test_writer_loads_only_the_repair_validator_when_requested(self) -> None:
        registry = object()
        writer = object()
        with (
            patch.object(
                self.runner,
                "EvidenceValidatorRegistry",
                return_value=registry,
            ) as registry_factory,
            patch.object(
                self.runner,
                "StateWriter",
                return_value=writer,
            ) as writer_factory,
            patch.object(self.runner, "PermitKeyStore") as key_store,
            patch.object(
                self.runner,
                "PermitAuthority",
                return_value="permit-authority",
            ),
        ):
            self.assertIs(self.runner._writer(), writer)
            registry_factory.assert_called_once_with(())
            writer_factory.assert_called_once_with(
                self.runner.ROOT,
                permit_authority=None,
                validation_registry=registry,
            )
            key_store.assert_not_called()

            registry_factory.reset_mock()
            writer_factory.reset_mock()
            key_store.return_value.load_or_create.return_value = b"key"
            self.assertIs(
                self.runner._writer(include_repair_validator=True),
                writer,
            )
            validators = registry_factory.call_args.args[0]
            self.assertEqual(len(validators), 1)
            self.assertEqual(
                validators[0].validator_id,
                self.runner.EXPECTED_REPAIR_VALIDATOR_ID,
            )
            writer_factory.assert_called_once_with(
                self.runner.ROOT,
                permit_authority="permit-authority",
                validation_registry=registry,
            )
            key_store.assert_called_once_with(
                self.runner.ROOT / "local" / "permit.key"
            )

if __name__ == "__main__":
    unittest.main()
