from __future__ import annotations

from dataclasses import replace
import importlib.util
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.running_job import RunningJobAuthorityIntegrityError
from axiom_rift.operations.writer import StateWriter, ready_control_body
from axiom_rift.storage.index import IndexRecord, LocalIndex, _record_digest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "verify_analog_fit_v2_parity.py"


def load_script():
    spec = importlib.util.spec_from_file_location(
        "verify_analog_fit_v2_parity",
        SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class AnalogFitV2ParityAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        workspace = Path(self.temporary.name).resolve()
        self.root = workspace / "repository"
        self.foundation_root = workspace / "foundation"
        authority = ready_control_body()["authority"]
        relative_paths = [
            authority["operating_direction"],
            *authority["contracts"],
            *authority["foundation_inputs"],
        ]
        for relative in relative_paths:
            destination = self.foundation_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO_ROOT / relative, destination)
        self.writer = StateWriter(
            self.root,
            engineering_fixture=True,
            foundation_root=self.foundation_root,
        )
        self.writer.initialize_ready()
        self.module = load_script()
        self.record_id = "reference-completion:fixture"
        self.output_name = "scientific/fixture/evaluation-trace.json"
        artifact = self.writer.evidence.finalize(
            canonical_bytes({"schema": "fixture-trace.v1"})
        )
        self.trace_sha256 = artifact.sha256
        record = IndexRecord(
            kind="job-completed",
            record_id=self.record_id,
            subject="Job:fixture",
            status="succeeded",
            fingerprint=canonical_digest(
                domain="analog-parity-authority-fixture",
                payload={
                    "output_name": self.output_name,
                    "trace_sha256": self.trace_sha256,
                },
            ),
            payload={
                "outputs": {self.output_name: self.trace_sha256},
            },
        )

        def prepare(current, _index):
            assert current is not None
            return self.writer._body(current), [record], {"seeded": True}

        self.writer._commit(
            event_kind="legacy_analog_parity_fixture_seeded",
            operation_id="seed-authenticated-analog-parity-reference",
            subject="Job:fixture",
            payload={"trial_delta": 0},
            prepare=prepare,
        )

    def _reference_trace(self):
        with (
            patch.object(
                self.module,
                "REFERENCE_COMPLETION_RECORD_ID",
                self.record_id,
            ),
            patch.object(
                self.module,
                "REFERENCE_TRACE_OUTPUT",
                self.output_name,
            ),
            patch.object(
                self.module,
                "REFERENCE_TRACE_SHA256",
                self.trace_sha256,
            ),
            patch.object(
                self.module,
                "extract_analog_family_trace_from_subject",
                return_value={"authenticated": True},
            ),
        ):
            return self.module._reference_trace(
                self.root,
                foundation_root=self.foundation_root,
            )

    def test_reference_completion_is_read_through_authenticated_boundary(
        self,
    ) -> None:
        self.assertEqual(self._reference_trace(), {"authenticated": True})

    def test_forged_reference_completion_record_fails_closed(self) -> None:
        with LocalIndex(self.writer.index_path) as index:
            record = index.get("job-completed", self.record_id)
            assert record is not None
            tampered = replace(record, status="forged")
            payload_json = canonical_bytes(dict(tampered.payload)).decode("ascii")
            index._connection.execute(  # noqa: SLF001 - adversarial fixture
                "UPDATE records SET status = ?, record_digest = ? "
                "WHERE kind = ? AND record_id = ?",
                (
                    tampered.status,
                    _record_digest(tampered, payload_json),
                    tampered.kind,
                    tampered.record_id,
                ),
            )
            index._connection.execute(  # noqa: SLF001 - adversarial fixture
                "UPDATE projection_stats SET projection_valid = 1 "
                "WHERE singleton = 1"
            )

        with self.assertRaisesRegex(
            RunningJobAuthorityIntegrityError,
            "not a unique Journal member",
        ):
            self._reference_trace()

    def test_files_are_ascii_and_script_has_no_raw_sqlite_reader(self) -> None:
        source = SCRIPT.read_text(encoding="ascii")
        Path(__file__).read_text(encoding="ascii")
        self.assertNotIn("import sqlite3", source)
        self.assertNotIn("sqlite3.connect", source)
        self.assertIn("RunningJobAuthority", source)
        self.assertIn("open_stable_index", source)


if __name__ == "__main__":
    unittest.main()
