from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import axiom_rift.operations.study_close_git as study_close_git
from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.study_close_git import (
    CHECKPOINT_PATH,
    StudyCloseDeliveryError,
    audit_all_study_close_deliveries,
    initialize_study_close_delivery_checkpoint,
    prepare_study_close_delivery_checkpoint,
    render_projection,
    require_all_study_close_deliveries,
    require_study_close_guard_ready,
    validate_commit_message,
)
from axiom_rift.operations.writer import StateWriter,TransitionError
from axiom_rift.storage.journal import _render_manifest, _render_seal


EXECUTABLE_ID = "executable:" + "b" * 64


def run(root: Path, *arguments: str) -> None:
    subprocess.run(arguments, cwd=root, check=True, capture_output=True)


def close_event(
    *,
    sequence: int = 1,
    previous_event_id: str | None = None,
    journal_offset: int = 0,
    study_id: str = "STU-TEST",
    kpi_sequence: int = 1,
) -> dict[str, object]:
    base: dict[str, object] = {
        "schema": "journal_event",
        "sequence": sequence,
        "previous_event_id": previous_event_id,
        "journal_offset": journal_offset,
        "event_kind": "study_closed",
        "operation_id": f"close-{study_id.lower()}",
        "subject": f"Study:{study_id}",
        "payload": {},
        "control": {},
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
                    "sequence": kpi_sequence,
                    "study_id": study_id,
                },
            }
        ],
        "index_record_count": sequence + 1,
        "index_projection_digest": "c" * 64,
        "occurred_at_utc": "2026-07-12T00:00:00Z",
    }
    return {
        **base,
        "event_id": canonical_digest(domain="journal-event", payload=base),
    }


def fixture_event() -> dict[str, object]:
    base: dict[str, object] = {
        "schema": "journal_event",
        "sequence": 1,
        "previous_event_id": None,
        "journal_offset": 0,
        "event_kind": "fixture_recorded",
        "operation_id": "fixture-one",
        "subject": "Fixture:Git",
        "payload": {},
        "control": {},
        "index_records": [],
        "index_record_count": 1,
        "index_projection_digest": "d" * 64,
        "occurred_at_utc": "2026-07-11T00:00:00Z",
    }
    return {
        **base,
        "event_id": canonical_digest(domain="journal-event", payload=base),
    }


EVENT_ID = str(close_event()["event_id"])


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
        (self.root / ".githooks").mkdir()
        hook = self.root / ".githooks" / "commit-msg"
        hook.write_text(
            '#!/bin/sh\nexec python scripts/validate_study_close_commit.py "$1"\n',
            encoding="ascii",
        )
        run(self.root, "git", "add", "--chmod=+x", ".githooks/commit-msg")
        run(self.root, "git", "config", "core.hooksPath", ".githooks")
        event = close_event()
        self.events = [event]
        (self.root / "records" / "journal.jsonl").write_bytes(
            canonical_bytes(event) + b"\n"
        )
        (self.root / "state" / "control.json").write_text(
            json.dumps(
                {
                    "heads": {
                        "journal": {"event_id": EVENT_ID, "sequence": 1}
                    },
                    "revision": 1,
                },
                separators=(",", ":"),
            ),
            encoding="ascii",
        )
        (self.root / "records" / "STUDY_KPI.md").write_bytes(
            render_projection(self.events)
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

    def write_control(self, event: dict[str, object]) -> None:
        (self.root / "state" / "control.json").write_text(
            json.dumps(
                {
                    "heads": {
                        "journal": {
                            "event_id": event["event_id"],
                            "sequence": event["sequence"],
                        }
                    },
                    "revision": event["sequence"],
                },
                separators=(",", ":"),
            ),
            encoding="ascii",
        )

    def commit_initial_close(self) -> None:
        run(
            self.root,
            "git",
            "-c",
            "core.hooksPath=.git/hooks",
            "commit",
            "-F",
            str(self.message(valid=True)),
        )

    def initialize_checkpoint(self) -> None:
        self.commit_initial_close()
        checkpoint = initialize_study_close_delivery_checkpoint(self.root)
        run(self.root, "git", "add", CHECKPOINT_PATH)
        message = self.root / "checkpoint-init.txt"
        message.write_text(
            "Initialize audited Study-close delivery checkpoint\n\n"
            f"Axiom-Study-Close-Checkpoint: {checkpoint.checkpoint_digest}\n"
            f"Axiom-State-Revision: {checkpoint.cursor.sequence}\n",
            encoding="ascii",
        )
        validate_commit_message(self.root, message)
        run(
            self.root,
            "git",
            "-c",
            "core.hooksPath=.git/hooks",
            "commit",
            "-F",
            str(message),
        )
        require_all_study_close_deliveries(self.root)

    def append_committed_close(
        self,
        ordinal: int,
        *,
        valid_trailers: bool = True,
        valid_kpi: bool = True,
        advance_checkpoint: bool = True,
    ) -> dict[str, object]:
        journal = self.root / "records" / "journal.jsonl"
        content = journal.read_bytes()
        previous = self.events[-1]
        event = close_event(
            sequence=int(previous["sequence"]) + 1,
            previous_event_id=str(previous["event_id"]),
            journal_offset=len(content),
            study_id=f"STU-{ordinal:04d}",
            kpi_sequence=ordinal,
        )
        journal.write_bytes(content + canonical_bytes(event) + b"\n")
        self.events.append(event)
        self.write_control(event)
        (self.root / "records" / "STUDY_KPI.md").write_bytes(
            render_projection(self.events) if valid_kpi else b"broken KPI\n"
        )
        run(self.root, "git", "add", "state", "records")
        if advance_checkpoint and study_close_git._head_checkpoint(self.root) is not None:
            prepare_study_close_delivery_checkpoint(self.root)
            run(self.root, "git", "add", CHECKPOINT_PATH)
        message = self.root / f"close-{ordinal}.txt"
        text = f"Close {event['subject']}\n"
        if valid_trailers:
            text += (
                f"\nAxiom-Study-Close: {event['event_id']}\n"
                f"Axiom-State-Revision: {event['sequence']}\n"
            )
        message.write_text(text, encoding="ascii")
        run(
            self.root,
            "git",
            "-c",
            "core.hooksPath=.git/hooks",
            "commit",
            "-F",
            str(message),
        )
        return event

    def convert_to_segmented(self) -> None:
        legacy = self.root / "records" / "journal.jsonl"
        content = legacy.read_bytes()
        legacy.unlink()
        directory = self.root / "records" / "journal"
        directory.mkdir()
        (directory / "journal-000001.jsonl").write_bytes(content)
        (directory / "manifest.json").write_bytes(
            _render_manifest(
                sealed_segments=(),
                active_segment={
                    "id": "000001",
                    "path": "records/journal/journal-000001.jsonl",
                    "start_offset": 0,
                    "first_sequence": 1,
                    "previous_event_id": None,
                },
            )
        )
        run(self.root, "git", "add", "-A", "records")

    def test_exact_staged_snapshot_and_trailers_pass(self) -> None:
        validate_commit_message(self.root, self.message(valid=True))

    def test_missing_trailers_are_rejected(self) -> None:
        with self.assertRaisesRegex(StudyCloseDeliveryError, "exact"):
            validate_commit_message(self.root, self.message(valid=False))

    def test_tracked_commit_trigger_is_required(self) -> None:
        require_study_close_guard_ready(self.root)
        run(self.root, "git", "config", "--unset", "core.hooksPath")
        with self.assertRaisesRegex(StudyCloseDeliveryError, "hooksPath"):
            require_study_close_guard_ready(self.root)

    def test_modified_commit_trigger_is_rejected(self) -> None:
        (self.root / ".githooks" / "commit-msg").write_text(
            "#!/bin/sh\nexit 0\n", encoding="ascii"
        )
        with self.assertRaisesRegex(StudyCloseDeliveryError, "differs"):
            require_study_close_guard_ready(self.root)

    def test_partial_projection_staging_is_rejected(self) -> None:
        run(self.root, "git", "reset")
        run(self.root, "git", "add", "records/journal.jsonl")
        with self.assertRaisesRegex(StudyCloseDeliveryError, "together"):
            validate_commit_message(self.root, self.message(valid=True))

    def test_committed_checkpoint_passes_full_audit(self) -> None:
        message = self.message(valid=True)
        run(
            self.root,
            "git",
            "-c",
            "core.hooksPath=.git/hooks",
            "commit",
            "-F",
            str(message),
        )
        require_all_study_close_deliveries(self.root)

    def test_segmented_staged_snapshot_and_trailers_pass(self) -> None:
        self.convert_to_segmented()
        validate_commit_message(self.root, self.message(valid=True))

    def test_segmented_committed_checkpoint_passes_full_audit(self) -> None:
        self.convert_to_segmented()
        message = self.message(valid=True)
        run(
            self.root,
            "git",
            "-c",
            "core.hooksPath=.git/hooks",
            "commit",
            "-F",
            str(message),
        )
        require_all_study_close_deliveries(self.root)

    def test_segmented_active_path_is_required(self) -> None:
        self.convert_to_segmented()
        run(self.root, "git", "reset")
        run(self.root, "git", "add", "state/control.json")
        run(self.root, "git", "add", "records/STUDY_KPI.md")
        run(self.root, "git", "add", "records/journal/manifest.json")
        with self.assertRaisesRegex(StudyCloseDeliveryError, "complete|staged"):
            validate_commit_message(self.root, self.message(valid=True))

    def test_rotation_and_study_close_are_one_valid_checkpoint(self) -> None:
        run(self.root, "git", "reset")
        event_one = fixture_event()
        first_frame = canonical_bytes(event_one) + b"\n"
        legacy = self.root / "records" / "journal.jsonl"
        legacy.unlink()
        directory = self.root / "records" / "journal"
        directory.mkdir()
        segment_one = directory / "journal-000001.jsonl"
        segment_one.write_bytes(first_frame)
        (directory / "manifest.json").write_bytes(
            _render_manifest(
                sealed_segments=(),
                active_segment={
                    "id": "000001",
                    "path": "records/journal/journal-000001.jsonl",
                    "start_offset": 0,
                    "first_sequence": 1,
                    "previous_event_id": None,
                },
            )
        )
        self.write_control(event_one)
        (self.root / "records" / "STUDY_KPI.md").write_bytes(
            render_projection([event_one])
        )
        run(self.root, "git", "add", "-A", "state", "records", ".githooks")
        run(
            self.root,
            "git",
            "-c",
            "core.hooksPath=.git/hooks",
            "commit",
            "-m",
            "Seed segmented Journal fixture",
        )

        event_two = close_event(
            sequence=2,
            previous_event_id=str(event_one["event_id"]),
            journal_offset=len(first_frame),
        )
        descriptor = {
            "id": "000001",
            "path": "records/journal/journal-000001.jsonl",
            "seal_path": "records/journal/journal-000001.seal.json",
            "start_offset": 0,
            "byte_length": len(first_frame),
            "first_sequence": 1,
            "last_sequence": 1,
            "first_event_id": event_one["event_id"],
            "last_event_id": event_one["event_id"],
            "sha256": sha256(first_frame).hexdigest(),
        }
        (directory / "journal-000001.seal.json").write_bytes(
            _render_seal(descriptor)
        )
        (directory / "journal-000002.jsonl").write_bytes(
            canonical_bytes(event_two) + b"\n"
        )
        (directory / "manifest.json").write_bytes(
            _render_manifest(
                sealed_segments=(descriptor,),
                active_segment={
                    "id": "000002",
                    "path": "records/journal/journal-000002.jsonl",
                    "start_offset": len(first_frame),
                    "first_sequence": 2,
                    "previous_event_id": event_one["event_id"],
                },
            )
        )
        self.write_control(event_two)
        (self.root / "records" / "STUDY_KPI.md").write_bytes(
            render_projection([event_one, event_two])
        )
        run(self.root, "git", "add", "state/control.json")
        run(self.root, "git", "add", "records/STUDY_KPI.md")
        run(self.root, "git", "add", "records/journal")
        message = self.root / "rotation-message.txt"
        message.write_text(
            "Close Study after rotation\n\n"
            f"Axiom-Study-Close: {event_two['event_id']}\n"
            "Axiom-State-Revision: 2\n",
            encoding="ascii",
        )
        validate_commit_message(self.root, message)
        run(
            self.root,
            "git",
            "-c",
            "core.hooksPath=.git/hooks",
            "commit",
            "-F",
            str(message),
        )
        require_all_study_close_deliveries(self.root)
        verifier = study_close_git._sealed_journal_verifier(str(self.root))
        with patch.object(
            verifier,
            "_read_and_verify_sealed_segment",
            wraps=verifier._read_and_verify_sealed_segment,
        ) as sealed_verification:
            require_all_study_close_deliveries(self.root)
            sealed_verification.assert_not_called()
            (directory / "journal-000001.seal.json").write_bytes(b"{}")
            with self.assertRaisesRegex(
                StudyCloseDeliveryError, "worktree Journal audit failed"
            ):
                require_all_study_close_deliveries(self.root)
            sealed_verification.assert_called_once()

    def test_routine_guard_is_checkpoint_and_suffix_bounded(self) -> None:
        self.initialize_checkpoint()
        self.append_committed_close(2)
        with patch.object(
            study_close_git, "_git", wraps=study_close_git._git
        ) as one_git, patch.object(
            study_close_git, "_perform_full_audit"
        ) as full_audit, patch.object(
            study_close_git, "_validate_snapshot"
        ) as snapshot_audit, patch.object(
            study_close_git,
            "_read_file_suffix",
            wraps=study_close_git._read_file_suffix,
        ) as suffix_read:
            require_all_study_close_deliveries(self.root)
        full_audit.assert_not_called()
        snapshot_audit.assert_not_called()
        self.assertLessEqual(one_git.call_count, 9)
        self.assertEqual(suffix_read.call_count, 0)

        for ordinal in range(3, 11):
            self.append_committed_close(ordinal)
        with patch.object(
            study_close_git, "_git", wraps=study_close_git._git
        ) as many_git, patch.object(
            study_close_git, "_perform_full_audit"
        ) as full_audit, patch.object(
            study_close_git, "_validate_snapshot"
        ) as snapshot_audit:
            require_all_study_close_deliveries(self.root)
        full_audit.assert_not_called()
        snapshot_audit.assert_not_called()
        self.assertEqual(many_git.call_count, one_git.call_count)

    def test_deleted_or_forged_local_cache_is_not_authority(self) -> None:
        self.initialize_checkpoint()
        cache = self.root / "local" / "study-close-delivery-audit.json"
        cache.parent.mkdir()
        cache.write_bytes(b"forged\n")
        with patch.object(
            study_close_git, "_perform_full_audit"
        ) as full_audit, patch.object(
            study_close_git, "_write_audit_cache"
        ) as cache_write:
            require_all_study_close_deliveries(self.root)
            cache.unlink()
            require_all_study_close_deliveries(self.root)
        full_audit.assert_not_called()
        cache_write.assert_not_called()

    def test_forged_cache_cannot_hide_close_without_checkpoint_advance(self) -> None:
        self.initialize_checkpoint()
        self.append_committed_close(2, advance_checkpoint=False)
        cache = self.root / "local" / "study-close-delivery-audit.json"
        cache.parent.mkdir()
        cache.write_bytes(canonical_bytes({"forged": True}) + b"\n")
        with self.assertRaisesRegex(StudyCloseDeliveryError, "after the tracked"):
            require_all_study_close_deliveries(self.root)

    def test_commit_hook_rejects_checkpoint_omission(self) -> None:
        self.initialize_checkpoint()
        journal = self.root / "records" / "journal.jsonl"
        content = journal.read_bytes()
        previous = self.events[-1]
        event = close_event(
            sequence=2,
            previous_event_id=str(previous["event_id"]),
            journal_offset=len(content),
            study_id="STU-0002",
            kpi_sequence=2,
        )
        journal.write_bytes(content + canonical_bytes(event) + b"\n")
        self.events.append(event)
        self.write_control(event)
        (self.root / "records" / "STUDY_KPI.md").write_bytes(
            render_projection(self.events)
        )
        run(self.root, "git", "add", "state", "records")
        message = self.root / "omitted-checkpoint.txt"
        message.write_text(
            "Close without checkpoint\n\n"
            f"Axiom-Study-Close: {event['event_id']}\n"
            "Axiom-State-Revision: 2\n",
            encoding="ascii",
        )
        with self.assertRaisesRegex(StudyCloseDeliveryError, "checkpoint|staged"):
            validate_commit_message(self.root, message)

    def test_checkpoint_worktree_tamper_is_rejected(self) -> None:
        self.initialize_checkpoint()
        path = self.root / CHECKPOINT_PATH
        path.write_bytes(path.read_bytes().replace(b"full_audit", b"full-audit"))
        with self.assertRaisesRegex(
            StudyCloseDeliveryError, "differs from local main|malformed"
        ):
            require_all_study_close_deliveries(self.root)

    def test_rewritten_checkpoint_commit_is_rejected(self) -> None:
        self.initialize_checkpoint()
        amended = self.root / "amended.txt"
        amended.write_text(
            "Rewrite checkpoint as an ordinary close\n\n"
            f"Axiom-Study-Close: {EVENT_ID}\n"
            "Axiom-State-Revision: 1\n",
            encoding="ascii",
        )
        run(
            self.root,
            "git",
            "-c",
            "core.hooksPath=.git/hooks",
            "commit",
            "--amend",
            "-F",
            str(amended),
        )
        with self.assertRaisesRegex(StudyCloseDeliveryError, "initialization"):
            require_all_study_close_deliveries(self.root)

    def test_repair_manifest_tamper_is_rejected_without_full_rebuild(self) -> None:
        self.initialize_checkpoint()
        (self.root / "records" / "STUDY_CLOSE_DELIVERY_REPAIR.json").write_bytes(
            canonical_bytes({"entries": []}) + b"\n"
        )
        with patch.object(
            study_close_git, "_perform_full_audit"
        ) as rebuild, self.assertRaisesRegex(
            StudyCloseDeliveryError, "repair manifest differs"
        ):
            require_all_study_close_deliveries(self.root)
        rebuild.assert_not_called()

    def test_layout_change_reads_only_suffix_and_not_history(self) -> None:
        self.initialize_checkpoint()
        self.convert_to_segmented()
        run(
            self.root,
            "git",
            "-c",
            "core.hooksPath=.git/hooks",
            "commit",
            "-m",
            "Migrate Journal layout",
        )
        with patch.object(study_close_git, "_perform_full_audit") as rebuild:
            require_all_study_close_deliveries(self.root)
        rebuild.assert_not_called()

    def test_tracked_boundary_tamper_is_rejected_without_rebuild(self) -> None:
        self.initialize_checkpoint()
        journal = self.root / "records" / "journal.jsonl"
        content = journal.read_bytes()
        journal.write_bytes(b"[" + content[1:])
        with patch.object(
            study_close_git, "_perform_full_audit"
        ) as rebuild, self.assertRaisesRegex(
            StudyCloseDeliveryError, "suffix is invalid"
        ):
            require_all_study_close_deliveries(self.root)
        rebuild.assert_not_called()

    def test_non_close_main_advance_does_not_revalidate_history(self) -> None:
        self.initialize_checkpoint()
        (self.root / "README.md").write_text("fixture\n", encoding="ascii")
        run(self.root, "git", "add", "README.md")
        run(
            self.root,
            "git",
            "-c",
            "core.hooksPath=.git/hooks",
            "commit",
            "-m",
            "Add fixture note",
        )
        with patch.object(
            study_close_git, "_validate_snapshot"
        ) as validation, patch.object(
            study_close_git, "_perform_full_audit"
        ) as full_audit:
            require_all_study_close_deliveries(self.root)
        validation.assert_not_called()
        full_audit.assert_not_called()

    def test_writer_guard_calls_delivery_audit_in_a_real_git_root(self) -> None:
        writer=object.__new__(StateWriter);writer.root=self.root;writer.engineering_fixture=False
        with patch("axiom_rift.operations.study_close_git.require_study_close_guard_ready") as ready,patch("axiom_rift.operations.study_close_git.require_all_study_close_deliveries") as audit:
            writer._require_study_close_delivery_guard();ready.assert_called_once_with(self.root);audit.assert_called_once_with(self.root)

    def test_writer_guard_converts_delivery_failure_to_transition_error(self)->None:
        writer=object.__new__(StateWriter);writer.root=self.root;writer.engineering_fixture=False
        with patch("axiom_rift.operations.study_close_git.require_all_study_close_deliveries",side_effect=StudyCloseDeliveryError("missing")):
            with self.assertRaisesRegex(TransitionError,"blocked"):writer._require_study_close_delivery_guard()

    def test_writer_guards_every_post_close_scientific_entry_boundary(self) -> None:
        writer = object.__new__(StateWriter)
        calls = {
            "Study": lambda: writer.open_study(
                study_id="STU-TEST",
                question={},
                material_identity="material",
                material_display_name="material",
                semantic_proposal={},
                permit=None,  # type: ignore[arg-type]
                operation_id="open-study",
            ),
            "Batch": lambda: writer.open_batch(
                batch_spec=None,  # type: ignore[arg-type]
                permit=None,  # type: ignore[arg-type]
                operation_id="open-batch",
            ),
            "Job": lambda: writer.declare_job(spec={}, operation_id="declare-job"),
            "Portfolio snapshot": lambda: writer.record_portfolio_snapshot(
                snapshot=None,  # type: ignore[arg-type]
                operation_id="record-snapshot",
            ),
            "Portfolio decision": lambda: writer.record_portfolio_decision(
                decision=None,  # type: ignore[arg-type]
                operation_id="record-decision",
            ),
            "Study diagnosis": lambda: writer.record_study_diagnosis(
                diagnosis=None,  # type: ignore[arg-type]
                operation_id="record-diagnosis",
            ),
            "Architecture review": lambda: writer.record_architecture_review(
                review=None,  # type: ignore[arg-type]
                operation_id="record-architecture-review",
            ),
            "Candidate freeze": lambda: writer.freeze_candidate(
                executable=None,  # type: ignore[arg-type]
                evidence_refs=(),
                operation_id="freeze-candidate",
            ),
        }
        for boundary, invoke in calls.items():
            with self.subTest(boundary=boundary), patch.object(
                writer,
                "_require_study_close_delivery_guard",
                side_effect=TransitionError("guard blocked boundary"),
            ):
                with self.assertRaisesRegex(TransitionError, "guard blocked"):
                    invoke()
