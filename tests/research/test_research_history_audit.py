from __future__ import annotations

from dataclasses import replace
import importlib.util
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
import axiom_rift.operations.running_job as running_job_module
from axiom_rift.operations.running_job import RunningJobAuthorityIntegrityError
from axiom_rift.operations.writer import StateWriter, ready_control_body
from axiom_rift.storage.index import IndexRecord, LocalIndex, _record_digest
from axiom_rift.storage.state import WriterLock, seal_control


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    REPO_ROOT
    / ".agents"
    / "skills"
    / "run-research-portfolio"
    / "scripts"
    / "audit_research_history.py"
)


def load_script():
    spec = importlib.util.spec_from_file_location("audit_research_history", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ResearchHistoryAuditTests(unittest.TestCase):
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
            source = REPO_ROOT / relative
            destination = self.foundation_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        self.writer = StateWriter(
            self.root,
            engineering_fixture=True,
            foundation_root=self.foundation_root,
        )
        self.writer.initialize_ready()
        self._seed_typed_history()
        self.module = load_script()

    @staticmethod
    def _record(
        kind: str,
        record_id: str,
        subject: str,
        status: str,
        payload: dict[str, object],
    ) -> IndexRecord:
        return IndexRecord(
            kind=kind,
            record_id=record_id,
            subject=subject,
            status=status,
            fingerprint=canonical_digest(
                domain="research-history-audit-fixture",
                payload={
                    "kind": kind,
                    "payload": payload,
                    "record_id": record_id,
                    "status": status,
                    "subject": subject,
                },
            ),
            payload=payload,
        )

    def _seed_typed_history(self) -> None:
        rows = [
            self._record(
                "study-open",
                "STU-0001",
                "Study:STU-0001",
                "open",
                {
                    "mechanism_family": "fixture-family",
                    "mission_id": "MIS-0001",
                    "portfolio_decision_id": "decision:fixture",
                    "primary_research_layer": "feature",
                    "question": {
                        "causal_question": (
                            "Does the typed feature add information?"
                        ),
                        "changed_variables": ["feature"],
                        "controlled_variables": ["label", "trade"],
                    },
                    "system_architecture_family": "architecture-family:fixture",
                },
            ),
            self._record(
                "study-close",
                "close-1",
                "Study:STU-0001",
                "not_supported",
                {},
            ),
            self._record(
                "study-kpi",
                "STU-0001",
                "Study:STU-0001",
                "not_supported",
                {"metrics": {"trade_count": 12}},
            ),
            self._record(
                "portfolio-decision",
                "decision:fixture",
                "Mission:MIS-0001",
                "deepen",
                {
                    "chosen_option_id": "chosen",
                    "options": [
                        {"action": "deepen", "option_id": "chosen"}
                    ],
                },
            ),
            self._record(
                "trial",
                "executable:fixture",
                "Batch:fixture",
                "evaluated",
                {
                    "executable": {
                        "component_manifests": [
                            {"protocol": "feature.fixture.v1"},
                            {"protocol": "model.fixture.v1"},
                        ]
                    },
                    "study_id": "STU-0001",
                },
            ),
            self._record(
                "negative-memory",
                "negative:fixture",
                "Executable:fixture",
                "durable",
                {
                    "reopen_condition": "new information only",
                    "study_id": "STU-0001",
                },
            ),
            self._record(
                "study-diagnosis",
                "diagnosis:fixture",
                "Study:STU-0001",
                "absent_information",
                {"confidence": "high"},
            ),
            self._record(
                "mission-close",
                "mission-close-1",
                "Mission:MIS-0001",
                "closed_no_candidate",
                {},
            ),
        ]

        def prepare(current, _index):
            assert current is not None
            return self.writer._body(current), rows, {"seeded": len(rows)}

        self.writer._commit(
            event_kind="legacy_research_history_fixture_seeded",
            operation_id="seed-authenticated-research-history",
            subject="Study:STU-0001",
            payload={"trial_delta": 0},
            prepare=prepare,
        )

    def _audit(self):
        return self.module.build_audit(
            self.root,
            foundation_root=self.foundation_root,
        )

    def test_audit_is_journal_authenticated_and_maps_typed_study_context(
        self,
    ) -> None:
        control = self.writer.read_control()
        assert control is not None

        audit = self._audit()

        self.assertEqual(
            audit["history_head"],
            {
                "event_id": control["heads"]["journal"]["event_id"],
                "revision": control["revision"],
            },
        )
        self.assertEqual(audit["summary"]["study_count"], 1)
        self.assertEqual(
            audit["summary"]["primary_research_layer_study_counts"],
            {"feature": 1},
        )
        self.assertEqual(
            audit["studies"][0]["component_domains"],
            ["feature", "model"],
        )
        self.assertEqual(
            audit["studies"][0]["evidence_state"],
            "absent_information",
        )
        self.assertEqual(audit["studies"][0]["diagnosis_confidence"], "high")
        self.assertEqual(audit["studies"][0]["portfolio_action"], "deepen")
        self.assertEqual(
            audit["studies"][0]["reopen_conditions"],
            ["new information only"],
        )

    def test_coherent_forged_control_and_projection_head_fail_closed(self) -> None:
        control = self.writer.read_control()
        assert control is not None
        forged_digest = "f" * 64
        forged = dict(control)
        forged["heads"] = {
            **control["heads"],
            "index": {
                **control["heads"]["index"],
                "required_projection_digest": forged_digest,
            },
        }
        forged = seal_control(forged)
        (self.root / "state" / "control.json").write_bytes(
            canonical_bytes(forged)
        )
        with LocalIndex(self.writer.index_path) as index:
            index._connection.execute(  # noqa: SLF001 - adversarial fixture
                "UPDATE projection_stats SET projection_digest = ? "
                "WHERE singleton = 1",
                (forged_digest,),
            )

        with self.assertRaisesRegex(
            RunningJobAuthorityIntegrityError,
            "control content differs from journal authority",
        ):
            self._audit()

    def test_forged_projection_record_fails_journal_membership(self) -> None:
        with LocalIndex(self.writer.index_path) as index:
            record = index.get("study-open", "STU-0001")
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
            self._audit()

    def test_projection_guard_mismatch_fails_closed(self) -> None:
        with LocalIndex(self.writer.index_path) as index:
            index._connection.execute(  # noqa: SLF001 - adversarial fixture
                "UPDATE projection_stats SET projection_valid = 0 "
                "WHERE singleton = 1"
            )

        with self.assertRaisesRegex(
            RunningJobAuthorityIntegrityError,
            "read-only local index",
        ):
            self._audit()

    def test_foundation_authority_drift_fails_closed(self) -> None:
        path = self.foundation_root / "OPERATING_DIRECTION.md"
        path.write_bytes(path.read_bytes() + b"\n")

        with self.assertRaisesRegex(
            RunningJobAuthorityIntegrityError,
            "authority or Foundation input content drifted",
        ):
            self._audit()

    def test_missing_writer_coordination_lock_fails_closed(self) -> None:
        self.writer.lock_path.unlink()

        with self.assertRaisesRegex(
            RunningJobAuthorityIntegrityError,
            "coordination lock",
        ):
            self._audit()
        self.assertFalse(self.writer.lock_path.exists())

    def test_active_writer_coordination_lock_fails_closed(self) -> None:
        def short_writer_lock(path, *, create_if_missing=True):
            return WriterLock(
                path,
                create_if_missing=create_if_missing,
                timeout_seconds=1,
            )

        with WriterLock(self.writer.lock_path):
            with patch.object(
                running_job_module,
                "WriterLock",
                short_writer_lock,
            ):
                with self.assertRaisesRegex(
                    RunningJobAuthorityIntegrityError,
                    "coordination lock",
                ):
                    self._audit()

    def test_files_are_ascii(self) -> None:
        SCRIPT.read_text(encoding="ascii")
        Path(__file__).read_text(encoding="ascii")


if __name__ == "__main__":
    unittest.main()
