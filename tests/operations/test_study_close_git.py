from __future__ import annotations

import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from axiom_rift.operations.study_close_git import (
    StudyCloseDeliveryError,
    render_projection,
    require_all_study_close_deliveries,
    validate_commit_message,
)
from axiom_rift.operations.writer import StateWriter,TransitionError


EVENT_ID = "a" * 64
EXECUTABLE_ID = "executable:" + "b" * 64


def run(root: Path, *arguments: str) -> None:
    subprocess.run(arguments, cwd=root, check=True, capture_output=True)


def close_event() -> dict[str, object]:
    return {
        "event_id": EVENT_ID,
        "event_kind": "study_closed",
        "index_records": [
            {
                "kind": "study-kpi",
                "payload": {
                    "executable_display_id": "EXE-" + "b" * 12,
                    "executable_id": EXECUTABLE_ID,
                    "metrics": {
                        "median_fold_profit_factor_milli": 1100,
                        "monthly_realized_exit_drawdown_share_of_gross_profit_ppm": 200000,
                        "net_profit_micropoints": 1000,
                        "trade_count": 100,
                    },
                    "outcome": "supported",
                    "provenance": "prospective_close",
                    "sequence": 1,
                    "study_id": "STU-TEST",
                },
            }
        ],
        "occurred_at_utc": "2026-07-12T00:00:00Z",
        "sequence": 1,
    }


class StudyCloseGitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        run(self.root, "git", "init", "-b", "main")
        run(self.root, "git", "config", "user.email", "test@example.invalid")
        run(self.root, "git", "config", "user.name", "Axiom Test")
        (self.root / "state").mkdir()
        (self.root / "records").mkdir()
        event = close_event()
        events = [event]
        (self.root / "records" / "journal.jsonl").write_text(
            json.dumps(event, separators=(",", ":")) + "\n", encoding="ascii"
        )
        (self.root / "state" / "control.json").write_text(
            json.dumps(
                {
                    "heads": {"journal": {"event_id": EVENT_ID}},
                    "revision": 1,
                },
                separators=(",", ":"),
            ),
            encoding="ascii",
        )
        (self.root / "records" / "STUDY_KPI.md").write_bytes(
            render_projection(events)
        )
        run(self.root, "git", "add", "state", "records")

    def message(self, *, valid: bool) -> Path:
        path = self.root / "message.txt"
        value = "Close Study\n"
        if valid:
            value += (
                f"\nAxiom-Study-Close: {EVENT_ID}\n"
                "Axiom-State-Revision: 1\n"
            )
        path.write_text(value, encoding="ascii")
        return path

    def test_exact_staged_snapshot_and_trailers_pass(self) -> None:
        validate_commit_message(self.root, self.message(valid=True))

    def test_missing_trailers_are_rejected(self) -> None:
        with self.assertRaisesRegex(StudyCloseDeliveryError, "exact"):
            validate_commit_message(self.root, self.message(valid=False))

    def test_partial_projection_staging_is_rejected(self) -> None:
        run(self.root, "git", "reset")
        run(self.root, "git", "add", "records/journal.jsonl")
        with self.assertRaisesRegex(StudyCloseDeliveryError, "together"):
            validate_commit_message(self.root, self.message(valid=True))

    def test_committed_checkpoint_passes_full_audit(self) -> None:
        message = self.message(valid=True)
        run(self.root, "git", "commit", "-F", str(message))
        require_all_study_close_deliveries(self.root)

    def test_writer_guard_calls_delivery_audit_in_a_real_git_root(self) -> None:
        writer=object.__new__(StateWriter);writer.root=self.root;writer.engineering_fixture=False
        with patch("axiom_rift.operations.study_close_git.require_all_study_close_deliveries") as audit:
            writer._require_study_close_delivery_guard();audit.assert_called_once_with(self.root)

    def test_writer_guard_converts_delivery_failure_to_transition_error(self)->None:
        writer=object.__new__(StateWriter);writer.root=self.root;writer.engineering_fixture=False
        with patch("axiom_rift.operations.study_close_git.require_all_study_close_deliveries",side_effect=StudyCloseDeliveryError("missing")):
            with self.assertRaisesRegex(TransitionError,"blocked"):writer._require_study_close_delivery_guard()
