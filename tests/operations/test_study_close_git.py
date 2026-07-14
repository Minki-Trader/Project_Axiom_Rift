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
    StudyCloseGuardCapability,
    audit_all_study_close_deliveries,
    check_study_close_delivery_checkpoint_maintenance,
    check_study_close_delivery_checkpoint_v2_upgrade,
    initialize_study_close_delivery_checkpoint,
    inspect_tracked_study_close_delivery,
    prepare_study_close_delivery_checkpoint,
    prepare_study_close_delivery_checkpoint_maintenance,
    prepare_study_close_delivery_checkpoint_v2_upgrade,
    render_projection,
    require_all_study_close_deliveries,
    require_study_close_guard_ready,
    validate_commit_message,
)
from axiom_rift.operations.study_close_checkpoint import (
    CHECKPOINT_SCHEMA,
    EMPTY_CLOSE_CHAIN_DIGEST,
    LEGACY_CHECKPOINT_SCHEMA,
    JournalDeliveryCursor,
    StudyCloseDeliveryCheckpoint,
    advance_close_chain,
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


def ordinary_event(
    *,
    sequence: int,
    previous_event_id: str,
    journal_offset: int,
) -> dict[str, object]:
    base: dict[str, object] = {
        "schema": "journal_event",
        "sequence": sequence,
        "previous_event_id": previous_event_id,
        "journal_offset": journal_offset,
        "event_kind": "fixture_recorded",
        "operation_id": f"fixture-{sequence}",
        "subject": "Fixture:Git",
        "payload": {},
        "control": {},
        "index_records": [],
        "index_record_count": sequence + 1,
        "index_projection_digest": "d" * 64,
        "occurred_at_utc": "2026-07-11T00:00:00Z",
    }
    return {
        **base,
        "event_id": canonical_digest(domain="journal-event", payload=base),
    }


def historical_close_event(
    *,
    sequence: int,
    previous_event_id: str | None,
    journal_offset: int,
) -> dict[str, object]:
    study_id = f"STU-{sequence:04d}"
    record_id = sha256(f"close:{study_id}".encode("ascii")).hexdigest()
    base: dict[str, object] = {
        "schema": "journal_event",
        "sequence": sequence,
        "previous_event_id": previous_event_id,
        "journal_offset": journal_offset,
        "event_kind": "study_closed",
        "operation_id": f"historical-close-{sequence}",
        "subject": f"Study:{study_id}",
        "payload": {},
        "control": {},
        "index_records": [
            {
                "kind": "study-close",
                "payload": {"outcome": "evidence_gap"},
                "record_id": record_id,
                "status": "evidence_gap",
                "subject": f"Study:{study_id}",
            }
        ],
        "index_record_count": sequence,
        "index_projection_digest": "e" * 64,
        "occurred_at_utc": f"2026-06-{sequence:02d}T00:00:00Z",
    }
    return {**base, "event_id": canonical_digest(domain="journal-event", payload=base)}


def historical_backfill_event(
    closes: list[dict[str, object]], *, journal_offset: int
) -> dict[str, object]:
    records: list[dict[str, object]] = []
    for sequence, close in enumerate(closes, start=1):
        close_record = close["index_records"][0]  # type: ignore[index]
        study_id = str(close["subject"]).removeprefix("Study:")
        records.append(
            {
                "event_sequence": sequence,
                "event_stream": "study-kpi",
                "fingerprint": sha256(f"kpi:{study_id}".encode("ascii")).hexdigest(),
                "kind": "study-kpi",
                "payload": {
                    "completion_record_id": None,
                    "executable_display_id": None,
                    "executable_id": None,
                    "historical_study_close_event_id": close["event_id"],
                    "historical_study_close_record_id": close_record["record_id"],  # type: ignore[index]
                    "historical_study_close_revision": close["sequence"],
                    "metrics": {
                        "median_fold_profit_factor_milli": None,
                        "monthly_realized_exit_drawdown_share_of_gross_profit_ppm": None,
                        "net_profit_micropoints": None,
                        "trade_count": None,
                    },
                    "outcome": "evidence_gap",
                    "provenance": "historical_backfill",
                    "sequence": sequence,
                    "source": "writer_derived_unavailable",
                    "study_id": study_id,
                    "unavailable_reason": "fixture",
                },
                "record_id": study_id,
                "status": "evidence_gap",
                "subject": f"Study:{study_id}",
            }
        )
    sequence = len(closes) + 1
    base: dict[str, object] = {
        "schema": "journal_event",
        "sequence": sequence,
        "previous_event_id": closes[-1]["event_id"],
        "journal_offset": journal_offset,
        "event_kind": "study_kpi_backfilled",
        "operation_id": "study-kpi-historical-backfill-v1",
        "subject": "ProjectGoal:OPERATING_DIRECTION.md",
        "payload": {
            "activation_operation_id": "study-close-kpi-main-delivery-authority-v1",
            "evidence": [],
        },
        "control": {},
        "index_records": records,
        "index_record_count": sequence + len(records),
        "index_projection_digest": "f" * 64,
        "occurred_at_utc": "2026-07-01T00:00:00Z",
    }
    return {**base, "event_id": canonical_digest(domain="journal-event", payload=base)}


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
        run(
            self.root,
            "git",
            "-c",
            "core.hooksPath=.git/hooks",
            "commit",
            "-m",
            "Seed Study-close guard fixture",
        )
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

    def install_legacy_checkpoint(self) -> StudyCloseDeliveryCheckpoint:
        self.commit_initial_close()
        control_content = (self.root / "state" / "control.json").read_bytes()
        kpi_content = (self.root / "records" / "STUDY_KPI.md").read_bytes()
        parent_main = subprocess.run(
            ("git", "rev-parse", "HEAD"),
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        legacy = StudyCloseDeliveryCheckpoint(
            basis="full_audit",
            parent_main=parent_main,
            previous_checkpoint_commit=None,
            previous_checkpoint_digest=None,
            cursor=JournalDeliveryCursor.from_events(
                self.events, journal_path="records/journal.jsonl"
            ),
            prospective_close_count=1,
            prospective_close_chain_digest=advance_close_chain(
                EMPTY_CLOSE_CHAIN_DIGEST, EVENT_ID, 1
            ),
            repair_manifest_digest=None,
            control_sha256=sha256(control_content).hexdigest(),
            kpi_sha256=sha256(kpi_content).hexdigest(),
            last_study_close_event_id=None,
            last_study_close_revision=None,
            schema=LEGACY_CHECKPOINT_SCHEMA,
        )
        (self.root / CHECKPOINT_PATH).write_bytes(legacy.render())
        run(self.root, "git", "add", CHECKPOINT_PATH)
        message = self.root / "legacy-checkpoint.txt"
        message.write_text(
            "Initialize legacy checkpoint\n\n"
            f"Axiom-Study-Close-Checkpoint: {legacy.checkpoint_digest}\n"
            "Axiom-State-Revision: 1\n",
            encoding="ascii",
        )
        run(
            self.root,
            "git",
            "-c",
            "core.hooksPath=.git/hooks",
            "commit",
            "-F",
            str(message),
        )
        return legacy

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

    def append_committed_non_close(self) -> dict[str, object]:
        journal = self.root / "records" / "journal.jsonl"
        content = journal.read_bytes()
        previous = self.events[-1]
        event = ordinary_event(
            sequence=int(previous["sequence"]) + 1,
            previous_event_id=str(previous["event_id"]),
            journal_offset=len(content),
        )
        journal.write_bytes(content + canonical_bytes(event) + b"\n")
        self.events.append(event)
        self.write_control(event)
        (self.root / "records" / "STUDY_KPI.md").write_bytes(
            render_projection(self.events)
        )
        run(self.root, "git", "add", "state", "records")
        run(
            self.root,
            "git",
            "-c",
            "core.hooksPath=.git/hooks",
            "commit",
            "-m",
            "Record ordinary Journal suffix",
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

    def test_real_guard_fails_closed_without_git_and_fixture_is_typed(self) -> None:
        with TemporaryDirectory() as directory:
            isolated = Path(directory)
            with self.assertRaisesRegex(
                StudyCloseDeliveryError, "verifiable Git repository"
            ):
                require_study_close_guard_ready(isolated)
            with self.assertRaisesRegex(
                StudyCloseDeliveryError, "verifiable Git repository"
            ):
                require_all_study_close_deliveries(isolated)
            require_study_close_guard_ready(
                isolated,
                capability=(
                    StudyCloseGuardCapability.ISOLATED_ENGINEERING_FIXTURE
                ),
            )
            require_all_study_close_deliveries(
                isolated,
                capability=(
                    StudyCloseGuardCapability.ISOLATED_ENGINEERING_FIXTURE
                ),
            )

    def test_delivery_commit_is_rejected_off_main(self) -> None:
        run(self.root, "git", "switch", "-c", "feature")
        with self.assertRaisesRegex(StudyCloseDeliveryError, "local main"):
            validate_commit_message(self.root, self.message(valid=True))

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

    def test_explicit_v1_to_v2_upgrade_is_checkable_and_hook_bound(self) -> None:
        self.install_legacy_checkpoint()

        projected = check_study_close_delivery_checkpoint_v2_upgrade(self.root)
        self.assertEqual(projected.schema, CHECKPOINT_SCHEMA)
        self.assertEqual(projected.basis, "checkpoint_upgrade")
        self.assertEqual(
            StudyCloseDeliveryCheckpoint.from_bytes(
                (self.root / CHECKPOINT_PATH).read_bytes()
            ).schema,
            LEGACY_CHECKPOINT_SCHEMA,
        )
        written = prepare_study_close_delivery_checkpoint_v2_upgrade(self.root)
        self.assertEqual(written, projected)
        run(self.root, "git", "add", CHECKPOINT_PATH)
        upgrade_message = self.root / "upgrade-checkpoint.txt"
        upgrade_message.write_text(
            "Upgrade tracked checkpoint v2\n\n"
            f"Axiom-Study-Close-Checkpoint: {written.checkpoint_digest}\n"
            f"Axiom-State-Revision: {written.cursor.sequence}\n",
            encoding="ascii",
        )
        validate_commit_message(self.root, upgrade_message)
        run(
            self.root,
            "git",
            "-c",
            "core.hooksPath=.git/hooks",
            "commit",
            "-F",
            str(upgrade_message),
        )
        with patch.object(
            study_close_git,
            "_ensure_origin_delivery_observed",
            side_effect=AssertionError("read-only inspection touched origin"),
        ), patch.object(
            study_close_git,
            "_best_effort_write_cache",
            side_effect=AssertionError("read-only inspection wrote cache"),
        ):
            inspected = inspect_tracked_study_close_delivery(self.root)
        self.assertEqual(inspected.checkpoint_digest, written.checkpoint_digest)
        require_all_study_close_deliveries(self.root)

    def test_v2_upgrade_rejects_uncommitted_repair_manifest_bytes(self) -> None:
        self.install_legacy_checkpoint()
        repair = self.root / "records" / "STUDY_CLOSE_DELIVERY_REPAIR.json"
        repair.write_bytes(canonical_bytes({"entries": []}) + b"\n")

        with self.assertRaisesRegex(
            StudyCloseDeliveryError, "authority bytes.*REPAIR"
        ):
            check_study_close_delivery_checkpoint_v2_upgrade(self.root)

        run(self.root, "git", "add", str(repair.relative_to(self.root)))
        with self.assertRaisesRegex(
            StudyCloseDeliveryError, "authority bytes.*REPAIR"
        ):
            check_study_close_delivery_checkpoint_v2_upgrade(self.root)

    def test_no_close_checkpoint_maintenance_is_explicit_and_hook_bound(self) -> None:
        self.initialize_checkpoint()
        previous = StudyCloseDeliveryCheckpoint.from_bytes(
            (self.root / CHECKPOINT_PATH).read_bytes()
        )
        event = self.append_committed_non_close()
        require_all_study_close_deliveries(self.root)

        projected = check_study_close_delivery_checkpoint_maintenance(self.root)
        self.assertEqual(projected.basis, "maintenance")
        self.assertEqual(projected.cursor.sequence, event["sequence"])
        self.assertEqual(
            projected.prospective_close_count,
            previous.prospective_close_count,
        )
        self.assertEqual(
            projected.prospective_close_chain_digest,
            previous.prospective_close_chain_digest,
        )
        written = prepare_study_close_delivery_checkpoint_maintenance(self.root)
        self.assertEqual(written, projected)
        run(self.root, "git", "add", CHECKPOINT_PATH)
        message = self.root / "maintenance-checkpoint.txt"
        message.write_text(
            "Advance no-close Study delivery cursor\n\n"
            f"Axiom-Study-Close-Checkpoint: {written.checkpoint_digest}\n"
            f"Axiom-State-Revision: {written.cursor.sequence}\n",
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
        with self.assertRaisesRegex(
            StudyCloseDeliveryError, "validation failed"
        ):
            check_study_close_delivery_checkpoint_maintenance(self.root)

    def test_origin_attempt_debt_is_bound_and_exact_checkpoint_can_deliver(self) -> None:
        self.initialize_checkpoint()
        receipt_path = self.root / "local" / "study-close-origin-attempt.json"
        receipt = json.loads(receipt_path.read_text(encoding="ascii"))
        head = subprocess.run(
            ("git", "rev-parse", "HEAD"),
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        checkpoint = StudyCloseDeliveryCheckpoint.from_bytes(
            (self.root / CHECKPOINT_PATH).read_bytes()
        )
        self.assertEqual(receipt["outcome"], "delivery_debt")
        self.assertEqual(receipt["attempt_main_head"], head)
        self.assertEqual(receipt["target_commit"], head)
        self.assertEqual(
            receipt["checkpoint_digest"], checkpoint.checkpoint_digest
        )

        study_close_git._ensure_origin_delivery_observed.cache_clear()
        with patch.object(study_close_git, "_run_origin_git") as origin_git:
            require_all_study_close_deliveries(self.root)
        origin_git.assert_not_called()

        remote_temporary = TemporaryDirectory()
        self.addCleanup(remote_temporary.cleanup)
        remote = Path(remote_temporary.name)
        run(remote, "git", "init", "--bare", "-b", "main")
        run(self.root, "git", "remote", "add", "origin", str(remote))
        receipt_path.unlink()
        study_close_git._ensure_origin_delivery_observed.cache_clear()
        require_all_study_close_deliveries(self.root)
        delivered = json.loads(receipt_path.read_text(encoding="ascii"))
        self.assertEqual(delivered["outcome"], "delivered")
        self.assertEqual(delivered["target_commit"], head)
        origin_main = subprocess.run(
            ("git", "rev-parse", "origin/main"),
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(origin_main, head)

        run(self.root, "git", "remote", "remove", "origin")
        run(
            self.root,
            "git",
            "update-ref",
            "refs/remotes/origin/main",
            head,
        )
        receipt_path.unlink()
        study_close_git._ensure_origin_delivery_observed.cache_clear()
        require_all_study_close_deliveries(self.root)
        stale = json.loads(receipt_path.read_text(encoding="ascii"))
        self.assertEqual(stale["observed_remote_before"], head)
        self.assertNotEqual(stale["fetch_returncode"], 0)
        self.assertNotEqual(stale["push_returncode"], 0)
        self.assertEqual(stale["outcome"], "delivery_debt")

    def test_v2_binds_exact_twenty_one_row_historical_backfill(self) -> None:
        closes: list[dict[str, object]] = []
        content = b""
        previous_event_id: str | None = None
        for sequence in range(1, 22):
            event = historical_close_event(
                sequence=sequence,
                previous_event_id=previous_event_id,
                journal_offset=len(content),
            )
            closes.append(event)
            content += canonical_bytes(event) + b"\n"
            previous_event_id = str(event["event_id"])
        journal = self.root / "records" / "journal.jsonl"
        journal.write_bytes(content)
        self.write_control(closes[-1])
        (self.root / "records" / "STUDY_KPI.md").write_bytes(
            render_projection(closes)
        )
        run(self.root, "git", "add", "state", "records")
        run(
            self.root,
            "git",
            "-c",
            "core.hooksPath=.git/hooks",
            "commit",
            "-m",
            "Seed immutable historical Study closes",
        )

        backfill = historical_backfill_event(closes, journal_offset=len(content))
        content += canonical_bytes(backfill) + b"\n"
        journal.write_bytes(content)
        all_events = [*closes, backfill]
        self.write_control(backfill)
        (self.root / "records" / "STUDY_KPI.md").write_bytes(
            render_projection(all_events)
        )
        run(self.root, "git", "add", "state", "records")
        message = self.root / "backfill-message.txt"
        message.write_text(
            "Backfill historical Study KPI ledger\n\n"
            f"Axiom-Study-KPI-Backfill: {backfill['event_id']}\n"
            f"Axiom-State-Revision: {backfill['sequence']}\n",
            encoding="ascii",
        )
        run(
            self.root,
            "git",
            "-c",
            "core.hooksPath=.git/hooks",
            "commit",
            "-F",
            str(message),
        )

        checkpoint = initialize_study_close_delivery_checkpoint(self.root)
        proof = checkpoint.historical_kpi_backfill
        self.assertIsNotNone(proof)
        assert proof is not None
        self.assertEqual(proof.event_id, backfill["event_id"])
        self.assertEqual(proof.revision, backfill["sequence"])
        self.assertEqual(len(proof.sources), 21)
        self.assertEqual(
            [source.kpi_sequence for source in proof.sources],
            list(range(1, 22)),
        )
        self.assertEqual(
            {binding.path for binding in proof.path_blobs},
            {
                "records/STUDY_KPI.md",
                "records/journal.jsonl",
                "state/control.json",
            },
        )
        self.assertTrue(study_close_git._ancestor(self.root, proof.commit, proof.ancestry_anchor))

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
        cache.parent.mkdir(exist_ok=True)
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
        cache.parent.mkdir(exist_ok=True)
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

    def test_real_writer_guard_fails_closed_without_git(self) -> None:
        with TemporaryDirectory() as directory:
            writer = object.__new__(StateWriter)
            writer.root = Path(directory)
            writer.engineering_fixture = False
            with self.assertRaisesRegex(TransitionError, "blocked"):
                writer._require_study_close_delivery_guard()

    def test_writer_accepts_only_an_isolated_typed_guard_capability(self) -> None:
        capability = StudyCloseGuardCapability.ISOLATED_ENGINEERING_FIXTURE
        with TemporaryDirectory() as directory:
            writer = StateWriter(
                directory,
                study_close_guard_capability=capability,
            )
            writer._require_study_close_delivery_guard()
        with self.assertRaisesRegex(TransitionError, "isolated non-Git fixture"):
            StateWriter(
                self.root,
                study_close_guard_capability=capability,
            )

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
