from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
from threading import Event, Thread
from typing import Any, Mapping
import unittest
from unittest.mock import patch

from axiom_rift.core.canonical import CanonicalJSONError
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.writer import (
    InjectedCrash,
    RecoveryRequired,
    StateWriter,
    TransitionError,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex
from axiom_rift.storage.journal import JournalIntegrityError
from axiom_rift.storage.state import ControlStateError, seal_control


FIXED_NOW = "2026-07-12T00:00:00Z"
REPO_ROOT = Path(__file__).resolve().parents[2]
AUTHORITY_PATHS = (
    "OPERATING_DIRECTION.md",
    "contracts/operations.yaml",
    "contracts/science.yaml",
    "contracts/evidence.yaml",
    "contracts/runtime.yaml",
    "foundation/market.yaml",
    "foundation/environment.yaml",
    "foundation/data.yaml",
    "foundation/data_exposure.yaml",
    "foundation/prior_scientific_memory.yaml",
    "foundation/origin.yaml",
)
RECOVERY_REJECTIONS = (
    FileNotFoundError,
    JournalIntegrityError,
    RuntimeError,
    TransitionError,
)


def file_sha256(content: bytes) -> str:
    return sha256(content).hexdigest()


def authority_paths(authority: Mapping[str, Any]) -> tuple[str, ...]:
    return (
        authority["operating_direction"],
        *authority["contracts"],
        *authority["foundation_inputs"],
    )


def authority_manifest_digest(contents: Mapping[str, bytes]) -> str:
    hashes = {
        relative: file_sha256(contents[relative])
        for relative in AUTHORITY_PATHS
    }
    return canonical_digest(domain="authority-manifest", payload=hashes)


class AuthorityMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.original_contents: dict[str, bytes] = {}
        for relative in AUTHORITY_PATHS:
            source = REPO_ROOT / relative
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            copyfile(source, target)
            self.original_contents[relative] = target.read_bytes()

        self.writer = StateWriter(
            self.root,
            clock=lambda: FIXED_NOW,
            engineering_fixture=True,
            foundation_root=self.root,
        )
        initialized = self.writer.initialize_ready()
        self.assertEqual(initialized.revision, 1)
        self.assertFalse(initialized.reused)
        ready = self.writer.read_control()
        assert ready is not None
        self.ready_control = deepcopy(ready)
        self.ready_journal = (self.root / "records" / "journal.jsonl").read_bytes()

    def replacements(self) -> dict[str, bytes]:
        return {
            "OPERATING_DIRECTION.md": (
                self.original_contents["OPERATING_DIRECTION.md"]
                + b"\n<!-- authority migration fixture -->\n"
            ),
            "contracts/runtime.yaml": (
                self.original_contents["contracts/runtime.yaml"]
                + b"\n# authority migration fixture\n"
            ),
        }

    def migrate(
        self,
        *,
        operation_id: str,
        reason: str = "exercise crash safe authority migration",
        crash_after: str | None = None,
        replacements: Mapping[str, bytes] | None = None,
    ):
        return self.writer.migrate_authority(
            replacements=self.replacements() if replacements is None else replacements,
            reason=reason,
            operation_id=operation_id,
            crash_after=crash_after,
        )

    def expected_contents(self) -> dict[str, bytes]:
        expected = dict(self.original_contents)
        expected.update(self.replacements())
        return expected

    def assert_authority_files(
        self, expected_contents: Mapping[str, bytes]
    ) -> None:
        observed_paths = tuple(
            relative
            for relative in AUTHORITY_PATHS
            if (self.root / relative).is_file()
        )
        self.assertEqual(observed_paths, AUTHORITY_PATHS)
        for relative in AUTHORITY_PATHS:
            self.assertEqual(
                (self.root / relative).read_bytes(),
                expected_contents[relative],
                relative,
            )

    def assert_staged_replacements(
        self,
        event: Mapping[str, Any],
        replacements: Mapping[str, bytes],
    ) -> tuple[Path, ...]:
        replacement_rows = event["payload"].get("replacements")
        self.assertIsInstance(replacement_rows, list)
        assert isinstance(replacement_rows, list)
        expected_rows = [
            {
                "artifact_sha256": file_sha256(replacements[relative]),
                "new_sha256": file_sha256(replacements[relative]),
                "old_sha256": file_sha256(self.original_contents[relative]),
                "path": relative,
            }
            for relative in sorted(replacements)
        ]
        self.assertEqual(replacement_rows, expected_rows)

        evidence = event["payload"].get("evidence")
        self.assertIsInstance(evidence, list)
        assert isinstance(evidence, list)
        expected_hashes = {file_sha256(content) for content in replacements.values()}
        observed_hashes = {item["sha256"] for item in evidence}
        self.assertEqual(observed_hashes, expected_hashes)
        self.assertEqual(len(evidence), len(replacements))

        paths: list[Path] = []
        for item in evidence:
            relative_path = item["relative_path"]
            path = self.root / "local" / "evidence" / relative_path
            self.assertTrue(path.is_file(), relative_path)
            content = path.read_bytes()
            self.assertEqual(len(content), item["size_bytes"])
            self.assertEqual(file_sha256(content), item["sha256"])
            paths.append(path)
        return tuple(paths)

    def assert_zero_scientific_delta(self, event: Mapping[str, Any]) -> None:
        payload = event["payload"]
        self.assertEqual(payload.get("scientific_claim"), "none")
        self.assertEqual(payload.get("trial_delta"), 0)
        self.assertEqual(payload.get("holdout_delta"), 0)

    def assert_completed_migration(self, operation_id: str) -> None:
        expected = self.expected_contents()
        expected_manifest = authority_manifest_digest(expected)
        control = self.writer.read_control()
        assert control is not None

        self.assertEqual(control["revision"], 2)
        self.assertEqual(control["heads"]["journal"]["sequence"], 2)
        self.assertEqual(control["heads"]["index"]["required_sequence"], 2)
        self.assertEqual(authority_paths(control["authority"]), AUTHORITY_PATHS)
        self.assertEqual(len(set(authority_paths(control["authority"]))), 11)
        self.assertEqual(
            control["authority"]["manifest_digest"], expected_manifest
        )
        self.assertEqual(
            self.writer._authority_manifest_digest(control["authority"]),
            expected_manifest,
        )
        self.assert_authority_files(expected)

        for key in (
            "initiative",
            "engineering",
            "scientific",
            "authorizations",
            "next_action",
        ):
            self.assertEqual(control[key], self.ready_control[key], key)

        events = self.writer.journal.read_all()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["sequence"], 1)
        self.assertEqual(events[1]["sequence"], 2)
        self.assertEqual(events[1]["previous_event_id"], events[0]["event_id"])
        self.assertEqual(events[1]["event_kind"], "authority_migrated")
        self.assertEqual(events[1]["operation_id"], operation_id)
        self.assertEqual(
            events[1]["control"]["authority"]["manifest_digest"],
            expected_manifest,
        )
        self.assert_staged_replacements(events[1], self.replacements())
        self.assert_zero_scientific_delta(events[1])
        self.assertTrue(
            (self.root / "records" / "journal.jsonl")
            .read_bytes()
            .startswith(self.ready_journal)
        )

    def test_migrates_old_one_event_ready_state_without_rewriting_history(self) -> None:
        initial_event = self.writer.journal.read_all()[0]

        result = self.migrate(operation_id="authority-migration-one-event")

        self.assertEqual(result.revision, 2)
        self.assertFalse(result.reused)
        self.assert_completed_migration("authority-migration-one-event")
        self.assertEqual(self.writer.journal.read_all()[0], initial_event)

    def test_after_journal_crash_recovers_files_cursor_and_index(self) -> None:
        operation_id = "authority-migration-after-journal"
        with self.assertRaises(InjectedCrash):
            self.migrate(operation_id=operation_id, crash_after="after_journal")

        control = self.writer.read_control()
        assert control is not None
        self.assertEqual(control["revision"], 1)
        events = self.writer.journal.read_all()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[-1]["event_kind"], "authority_migrated")
        self.assert_staged_replacements(events[-1], self.replacements())
        self.assert_authority_files(self.original_contents)

        report = self.writer.recover()

        self.assertEqual(report["journal_sequence"], 2)
        self.assert_completed_migration(operation_id)
        retried = self.migrate(operation_id=operation_id)
        self.assertTrue(retried.reused)
        self.assertEqual(retried.revision, 2)
        self.assertEqual(len(self.writer.journal.read_all()), 2)

    def test_after_authority_files_crash_recovers_cursor_and_index(self) -> None:
        operation_id = "authority-migration-after-files"
        with self.assertRaises(InjectedCrash):
            self.migrate(
                operation_id=operation_id,
                crash_after="after_authority_files",
            )

        control = self.writer.read_control()
        assert control is not None
        self.assertEqual(control["revision"], 1)
        self.assertEqual(len(self.writer.journal.read_all()), 2)
        self.assert_authority_files(self.expected_contents())

        report = self.writer.recover()

        self.assertEqual(report["journal_sequence"], 2)
        self.assert_completed_migration(operation_id)

    def test_same_operation_retry_is_idempotent_and_changed_input_is_rejected(
        self,
    ) -> None:
        operation_id = "authority-migration-idempotency"
        first = self.migrate(operation_id=operation_id)
        journal_after_first = (self.root / "records" / "journal.jsonl").read_bytes()

        second = self.migrate(operation_id=operation_id)

        self.assertFalse(first.reused)
        self.assertTrue(second.reused)
        self.assertEqual(second.event_id, first.event_id)
        self.assertEqual(second.revision, first.revision)
        self.assertEqual(
            (self.root / "records" / "journal.jsonl").read_bytes(),
            journal_after_first,
        )
        with self.assertRaises(TransitionError):
            self.migrate(
                operation_id=operation_id,
                reason="different authority migration reason",
            )
        self.assertEqual(
            (self.root / "records" / "journal.jsonl").read_bytes(),
            journal_after_first,
        )

    def test_concurrent_same_operation_reuses_the_committed_migration(self) -> None:
        operation_id = "authority-migration-concurrent-idempotency"
        reason = "exercise crash safe authority migration"
        replacements = self.replacements()
        competing = StateWriter(
            self.root,
            clock=lambda: FIXED_NOW,
            engineering_fixture=True,
            foundation_root=self.root,
        )
        snapshot_complete = Event()
        release_competing = Event()
        results: list[Any] = []
        failures: list[BaseException] = []
        original_finalize = competing.evidence.finalize

        def finalize_after_barrier(content: bytes):
            if not snapshot_complete.is_set():
                snapshot_complete.set()
                if not release_competing.wait(timeout=10):
                    raise RuntimeError("concurrent migration barrier timed out")
            return original_finalize(content)

        def run_competing() -> None:
            try:
                results.append(
                    competing.migrate_authority(
                        replacements=replacements,
                        reason=reason,
                        operation_id=operation_id,
                    )
                )
            except BaseException as exc:  # pragma: no cover - asserted in parent thread
                failures.append(exc)

        with patch.object(
            competing.evidence,
            "finalize",
            side_effect=finalize_after_barrier,
        ):
            thread = Thread(target=run_competing, daemon=True)
            thread.start()
            self.assertTrue(snapshot_complete.wait(timeout=10))
            try:
                committed = self.writer.migrate_authority(
                    replacements=replacements,
                    reason=reason,
                    operation_id=operation_id,
                )
            finally:
                release_competing.set()
                thread.join(timeout=10)

        self.assertFalse(thread.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(len(results), 1)
        self.assertFalse(committed.reused)
        self.assertTrue(results[0].reused)
        self.assertEqual(results[0].event_id, committed.event_id)
        self.assertEqual(results[0].revision, committed.revision)
        self.assertEqual(len(self.writer.journal.read_all()), 2)
        self.assert_completed_migration(operation_id)

    def test_active_mission_rejects_migration_without_touching_authority(self) -> None:
        self.writer.open_mission(
            mission_id="MIS-AUTHORITY-MIGRATION-GUARD",
            goal={
                "objective": "exercise the authority migration idle guard",
                "scope": ["isolated", "engineering_fixture"],
                "terminal_contract": "no_scientific_terminal",
            },
            operation_id="open-authority-migration-guard-mission",
        )
        journal_before = (self.root / "records" / "journal.jsonl").read_bytes()

        with self.assertRaises(TransitionError):
            self.migrate(operation_id="reject-active-mission-migration")

        self.assertEqual(
            (self.root / "records" / "journal.jsonl").read_bytes(),
            journal_before,
        )
        self.assert_authority_files(self.original_contents)

    def test_unlisted_authority_path_is_rejected_before_journal_append(self) -> None:
        with self.assertRaises((TransitionError, ValueError)):
            self.migrate(
                operation_id="reject-unlisted-authority-path",
                replacements={"README.md": b"unlisted authority staging\n"},
            )

        self.assertEqual(
            (self.root / "records" / "journal.jsonl").read_bytes(),
            self.ready_journal,
        )
        self.assert_authority_files(self.original_contents)

    def test_missing_staged_content_blocks_recovery_before_file_changes(self) -> None:
        with self.assertRaises(InjectedCrash):
            self.migrate(
                operation_id="authority-migration-missing-stage",
                crash_after="after_journal",
            )
        event = self.writer.journal.read_all()[-1]
        staged = self.assert_staged_replacements(event, self.replacements())
        staged[0].unlink()

        with self.assertRaises(RECOVERY_REJECTIONS):
            self.writer.recover()

        control = self.writer.read_control()
        assert control is not None
        self.assertEqual(control["revision"], 1)
        self.assert_authority_files(self.original_contents)

    def test_tampered_staged_content_blocks_recovery_before_file_changes(self) -> None:
        with self.assertRaises(InjectedCrash):
            self.migrate(
                operation_id="authority-migration-tampered-stage",
                crash_after="after_journal",
            )
        event = self.writer.journal.read_all()[-1]
        staged = self.assert_staged_replacements(event, self.replacements())
        staged[0].write_bytes(b"tampered authority staging\n")

        with self.assertRaises(RECOVERY_REJECTIONS):
            self.writer.recover()

        control = self.writer.read_control()
        assert control is not None
        self.assertEqual(control["revision"], 1)
        self.assert_authority_files(self.original_contents)

    def test_late_missing_stage_cannot_partially_replace_authority_files(self) -> None:
        with self.assertRaises(InjectedCrash):
            self.migrate(
                operation_id="authority-migration-late-missing-stage",
                crash_after="after_journal",
            )
        event = self.writer.journal.read_all()[-1]
        staged = self.assert_staged_replacements(event, self.replacements())
        self.assertGreaterEqual(len(staged), 2)
        staged[-1].unlink()

        with self.assertRaises(RECOVERY_REJECTIONS):
            self.writer.recover()

        control = self.writer.read_control()
        assert control is not None
        self.assertEqual(control["revision"], 1)
        self.assert_authority_files(self.original_contents)

    def test_future_index_rejection_precedes_authority_and_control_mutation(self) -> None:
        with self.assertRaises(InjectedCrash):
            self.migrate(
                operation_id="authority-migration-future-index",
                crash_after="after_journal",
            )
        with LocalIndex(self.writer.index_path) as index:
            index.put(
                IndexRecord(
                    kind="forged-future-index",
                    record_id="f" * 64,
                    subject="Fixture:future-index",
                    status="forged",
                    fingerprint="f" * 64,
                    payload={},
                    event_stream="control",
                    event_sequence=999,
                )
            )

        with self.assertRaises(JournalIntegrityError):
            self.writer.recover()

        control = self.writer.read_control()
        assert control is not None
        self.assertEqual(control["revision"], 1)
        self.assert_authority_files(self.original_contents)

    def test_invalid_authority_bytes_are_rejected_without_journal_delta(self) -> None:
        with self.assertRaises(TransitionError):
            self.migrate(
                operation_id="reject-invalid-authority-bytes",
                replacements={"contracts/runtime.yaml": b"\xff\x00not yaml\n"},
            )

        self.assertEqual(
            (self.root / "records" / "journal.jsonl").read_bytes(),
            self.ready_journal,
        )
        self.assertEqual(self.writer.read_control(), self.ready_control)
        self.assert_authority_files(self.original_contents)

    def test_ordinary_event_cannot_mutate_authority_control(self) -> None:
        def prepare(current, _index):
            assert current is not None
            body = self.writer._body(current)
            body["authority"]["unexpected"] = "untyped-authority-change"
            return body, [], {"changed": True}

        with self.assertRaises(TransitionError):
            self.writer._commit(
                event_kind="ordinary_authority_mutation_fixture",
                operation_id="reject-ordinary-authority-mutation",
                subject="Fixture:authority",
                payload={"fixture": True},
                prepare=prepare,
            )

        self.assertEqual(
            (self.root / "records" / "journal.jsonl").read_bytes(),
            self.ready_journal,
        )
        self.assertEqual(self.writer.read_control(), self.ready_control)
        self.assert_authority_files(self.original_contents)

    def test_deleted_control_recovers_across_repeated_path_migrations(self) -> None:
        relative = "OPERATING_DIRECTION.md"
        second_contents = self.replacements()[relative]
        third_contents = second_contents + b"\n<!-- second migration fixture -->\n"
        initial_event = self.writer.journal.read_all()[0]
        first = self.writer.migrate_authority(
            replacements={relative: second_contents},
            reason="first repeated path migration",
            operation_id="authority-migration-repeated-path-first",
        )
        self.writer.migrate_authority(
            replacements={relative: third_contents},
            reason="second repeated path migration",
            operation_id="authority-migration-repeated-path-second",
        )
        retried_first = self.writer.migrate_authority(
            replacements={relative: second_contents},
            reason="first repeated path migration",
            operation_id="authority-migration-repeated-path-first",
        )
        self.assertTrue(retried_first.reused)
        self.assertEqual(retried_first.event_id, first.event_id)
        self.assertEqual(retried_first.revision, first.revision)
        self.writer.control.path.unlink()

        report = self.writer.recover()

        expected = dict(self.original_contents)
        expected[relative] = third_contents
        control = self.writer.read_control()
        assert control is not None
        self.assertEqual(report["journal_sequence"], 3)
        self.assertTrue(report["control_repaired"])
        self.assertEqual(control["revision"], 3)
        self.assertEqual(
            control["authority"]["manifest_digest"],
            authority_manifest_digest(expected),
        )
        self.assert_authority_files(expected)
        self.assertEqual(self.writer.journal.read_all()[0], initial_event)

    def test_evidence_read_verifies_and_returns_one_read_buffer(self) -> None:
        content = b"single read authority evidence\n"
        artifact = self.writer.evidence.finalize(content)
        target = (
            self.root
            / "local"
            / "evidence"
            / "sha256"
            / artifact.sha256[:2]
            / artifact.sha256
        )
        with patch.object(
            type(target),
            "read_bytes",
            autospec=True,
            side_effect=[content, b"unverified second read\n"],
        ) as read_bytes:
            observed = self.writer.evidence.read_verified(artifact.sha256)

        self.assertEqual(observed, content)
        self.assertEqual(read_bytes.call_count, 1)

    def test_after_cursor_retry_requires_recovery_then_uses_bounded_lookup(self) -> None:
        operation_id = "authority-migration-after-cursor-retry"
        with self.assertRaises(InjectedCrash):
            self.migrate(operation_id=operation_id, crash_after="after_cursor")

        with self.assertRaises(RecoveryRequired):
            self.migrate(operation_id=operation_id)

        self.writer.recover()
        with patch.object(
            self.writer.journal,
            "read_all",
            side_effect=AssertionError("idempotent lookup replayed the Journal"),
        ):
            retried = self.migrate(operation_id=operation_id)
        self.assertTrue(retried.reused)
        self.assertEqual(retried.revision, 2)

    def test_control_rejects_bad_boundary_ids_paths_and_disposed_active_work(
        self,
    ) -> None:
        bad_path = deepcopy(self.ready_control)
        bad_path["authority"]["operating_direction"] = (
            "authority-" + chr(233) + ".md"
        )

        bad_successor = deepcopy(self.ready_control)
        bad_successor["next_action"] = {
            "kind": "await_root_goal",
            "predecessor_basis_record_id": "not-a-digest",
            "predecessor_mission_close_record_id": "also-not-a-digest",
            "predecessor_mission_id": "MIS-PREDECESSOR",
            "predecessor_outcome": "closed_no_candidate",
        }

        bad_external = deepcopy(self.ready_control)
        bad_external["next_action"] = {
            "basis_record_id": "a" * 64,
            "kind": "await_external_change",
            "predecessor_mission_close_record_id": "b" * 64,
            "predecessor_mission_id": "MIS-PREDECESSOR",
            "required_external_change": "change-" + chr(233),
        }

        disposed_with_work = deepcopy(self.ready_control)
        disposed_with_work["scientific"]["active_lineage"] = "LIN-LEFTOVER"

        for label, control in (
            ("non_ascii_authority_path", bad_path),
            ("bad_successor_digests", bad_successor),
            ("non_ascii_external_boundary", bad_external),
            ("disposed_active_work", disposed_with_work),
        ):
            with self.subTest(label=label), self.assertRaises(
                (CanonicalJSONError, ControlStateError)
            ):
                seal_control(control)


if __name__ == "__main__":
    unittest.main()
