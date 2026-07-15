from __future__ import annotations

import ast
import inspect
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from axiom_rift.operations.writer import StateWriter


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
        tree = ast.parse(inspect.getsource(StateWriter))
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
