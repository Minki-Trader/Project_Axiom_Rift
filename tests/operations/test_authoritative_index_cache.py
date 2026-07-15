from __future__ import annotations

import ast
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.operations.running_job import (
    RunningJobAuthority,
    RunningJobAuthorityIntegrityError,
)
from axiom_rift.operations.writer import RecoveryRequired, StateWriter
from axiom_rift.storage.index import (
    IndexIntegrityError,
    IndexRecord,
    LocalIndex,
    _record_digest,
)
from axiom_rift.storage.state import WriterLock


REPO_ROOT = Path(__file__).resolve().parents[2]


class AuthoritativeIndexCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.writer = StateWriter(
            Path(self.temporary.name).resolve(),
            engineering_fixture=True,
            foundation_root=REPO_ROOT,
        )
        self.writer.initialize_ready()
        control = self.writer.read_control()
        assert control is not None
        self.event_id = control["heads"]["journal"]["event_id"]
        self.record_id = "INI-0001:completed_ready_boundary"

    def _initiative_close(self) -> IndexRecord:
        with LocalIndex(self.writer.index_path) as index:
            record = index.get("initiative-close", self.record_id)
        assert record is not None
        return record

    def test_one_event_read_serves_repeated_rows_per_index_session(self) -> None:
        with patch.object(
            self.writer.journal,
            "read_event_at",
            wraps=self.writer.journal.read_event_at,
        ) as read_event:
            for _ in range(2):
                with self.writer._open_authoritative_index() as index:
                    self.assertIsNotNone(
                        index.get("initiative-close", self.record_id)
                    )
                    self.assertIsNotNone(index.get("journal-event", self.event_id))
                    self.assertIsNotNone(
                        index.get("initiative-close", self.record_id)
                    )

        self.assertEqual(read_event.call_count, 2)

    def test_writer_default_authoritative_index_has_no_mutation_capability(
        self,
    ) -> None:
        payload = self.writer.index_path.read_bytes()
        entries = {path.name for path in self.writer.index_path.parent.iterdir()}
        with self.writer._open_authoritative_index() as index:
            self.assertIsNotNone(index.get("initiative-close", self.record_id))
            self.assertFalse(hasattr(index, "put"))
            self.assertFalse(hasattr(index, "rebuild"))
            self.assertFalse(hasattr(index, "_connection"))
        self.assertEqual(self.writer.index_path.read_bytes(), payload)
        self.assertEqual(
            {path.name for path in self.writer.index_path.parent.iterdir()},
            entries,
        )

    def test_writer_mutable_index_helpers_have_exact_owners(self) -> None:
        source_path = (
            REPO_ROOT / "src" / "axiom_rift" / "operations" / "writer.py"
        )
        tree = ast.parse(source_path.read_text(encoding="ascii"))
        parents: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node

        owners: dict[str, list[str]] = {
            "_open_mutable_authoritative_index": [],
            "_open_mutable_recovery_index": [],
        }
        for node in ast.walk(tree):
            if (
                not isinstance(node, ast.Call)
                or not isinstance(node.func, ast.Attribute)
                or node.func.attr not in owners
            ):
                continue
            parent = parents.get(node)
            while parent is not None and not isinstance(
                parent,
                (ast.AsyncFunctionDef, ast.FunctionDef),
            ):
                parent = parents.get(parent)
            assert isinstance(parent, (ast.AsyncFunctionDef, ast.FunctionDef))
            owners[node.func.attr].append(parent.name)

        self.assertEqual(
            owners,
            {
                "_open_mutable_authoritative_index": ["_commit"],
                "_open_mutable_recovery_index": ["recover"],
            },
        )

    def test_duplicate_journal_member_remains_fail_closed(self) -> None:
        record = self._initiative_close()
        event = self.writer.journal.read_event_at(
            offset=record.authority_offset,  # type: ignore[arg-type]
            expected_sequence=record.authority_sequence,  # type: ignore[arg-type]
            expected_event_id=record.authority_event_id,  # type: ignore[arg-type]
        )
        projected = self.writer._index_mapping(record)
        self.assertEqual(event["index_records"].count(projected), 1)
        duplicate_event = dict(event)
        duplicate_event["index_records"] = [
            *event["index_records"],
            projected,
        ]

        with patch.object(
            self.writer.journal,
            "read_event_at",
            return_value=duplicate_event,
        ):
            with self.writer._open_authoritative_index() as index:
                with self.assertRaisesRegex(
                    IndexIntegrityError,
                    "not a unique Journal member",
                ):
                    index.get(record.kind, record.record_id)

    def test_non_member_remains_fail_closed(self) -> None:
        record = self._initiative_close()
        non_member = IndexRecord(
            kind=record.kind,
            record_id=record.record_id,
            subject=record.subject,
            status="non-member",
            fingerprint=record.fingerprint,
            payload=record.payload,
            event_stream=record.event_stream,
            event_sequence=record.event_sequence,
            authority_sequence=record.authority_sequence,
            authority_event_id=record.authority_event_id,
            authority_offset=record.authority_offset,
        )

        with self.writer._open_mutable_authoritative_index() as index:
            validator = index._authority_validator  # noqa: SLF001 - authority attack
            assert validator is not None
            with self.assertRaisesRegex(
                IndexIntegrityError,
                "not a unique Journal member",
            ):
                validator(non_member)

    def test_cached_event_still_rejects_tampered_projection_row(self) -> None:
        with patch.object(
            self.writer.journal,
            "read_event_at",
            wraps=self.writer.journal.read_event_at,
        ) as read_event:
            with self.writer._open_mutable_authoritative_index() as index:
                record = index.get("initiative-close", self.record_id)
                assert record is not None
                tampered = IndexRecord(
                    kind=record.kind,
                    record_id=record.record_id,
                    subject=record.subject,
                    status="tampered",
                    fingerprint=record.fingerprint,
                    payload=record.payload,
                    event_stream=record.event_stream,
                    event_sequence=record.event_sequence,
                    authority_sequence=record.authority_sequence,
                    authority_event_id=record.authority_event_id,
                    authority_offset=record.authority_offset,
                )
                payload_json = canonical_bytes(dict(tampered.payload)).decode("ascii")
                index._connection.execute(  # noqa: SLF001 - adversarial row edit
                    "UPDATE records SET status = ?, record_digest = ? "
                    "WHERE kind = ? AND record_id = ?",
                    (
                        tampered.status,
                        _record_digest(tampered, payload_json),
                        tampered.kind,
                        tampered.record_id,
                    ),
                )
                with self.assertRaisesRegex(
                    IndexIntegrityError,
                    "not a unique Journal member",
                ):
                    index.get(tampered.kind, tampered.record_id)

        self.assertEqual(read_event.call_count, 1)

    def test_public_stable_snapshot_is_authenticated_and_read_only(self) -> None:
        authority = RunningJobAuthority(
            self.writer.root,
            foundation_root=REPO_ROOT,
        )
        with authority.open_stable_index() as (control, index):
            record = index.get("initiative-close", self.record_id)
            self.assertIsNotNone(record)
            self.assertEqual(control["revision"], 1)
            self.assertFalse(hasattr(index, "put"))
            self.assertFalse(hasattr(index, "rebuild"))

        with LocalIndex(self.writer.index_path) as index:
            index._connection.execute(  # noqa: SLF001 - adversarial view test
                "UPDATE projection_stats SET projection_valid = 0 "
                "WHERE singleton = 1"
            )
        with self.assertRaisesRegex(
            RunningJobAuthorityIntegrityError,
            "read-only local index",
        ):
            with authority.open_stable_index():
                pass

    def test_writer_management_snapshot_rejects_forged_projection_row(
        self,
    ) -> None:
        with LocalIndex(self.writer.index_path) as index:
            index._connection.execute(  # noqa: SLF001 - adversarial row edit
                "UPDATE records SET status = ? WHERE kind = ? AND record_id = ?",
                ("forged", "initiative-close", self.record_id),
            )

        with self.assertRaisesRegex(RecoveryRequired, "read-only local index"):
            with self.writer.open_stable_index() as (_control, index):
                index.get("initiative-close", self.record_id)

    def test_writer_management_snapshot_rejects_active_writer_lock(
        self,
    ) -> None:
        index_payload = self.writer.index_path.read_bytes()
        lock_payload = self.writer.lock_path.read_bytes()
        entries = {path.name for path in self.writer.index_path.parent.iterdir()}

        def short_lock(path, *, create_if_missing=True):
            return WriterLock(
                path,
                timeout_seconds=1,
                create_if_missing=create_if_missing,
            )

        with WriterLock(self.writer.lock_path):
            with patch(
                "axiom_rift.operations.running_job.WriterLock",
                side_effect=short_lock,
            ):
                with self.assertRaisesRegex(
                    RecoveryRequired,
                    "coordination lock",
                ):
                    with self.writer.open_stable_index():
                        self.fail("active writer lock must fail closed")

        self.assertEqual(self.writer.index_path.read_bytes(), index_payload)
        self.assertEqual(self.writer.lock_path.read_bytes(), lock_payload)
        self.assertEqual(
            {path.name for path in self.writer.index_path.parent.iterdir()},
            entries,
        )

    def test_writer_management_snapshot_never_recreates_missing_index(
        self,
    ) -> None:
        self.writer.index_path.unlink()
        entries = {path.name for path in self.writer.index_path.parent.iterdir()}
        with self.assertRaisesRegex(RecoveryRequired, "read-only local index"):
            with self.writer.open_stable_index():
                self.fail("missing projection must fail closed")
        self.assertFalse(self.writer.index_path.exists())
        self.assertEqual(
            {path.name for path in self.writer.index_path.parent.iterdir()},
            entries,
        )

    def test_read_authority_never_creates_missing_repository_state(self) -> None:
        root = Path(self.temporary.name) / "absent-repository"
        authority = RunningJobAuthority(root, foundation_root=REPO_ROOT)
        self.assertFalse(root.exists())
        self.assertIsNone(authority.read_control())
        self.assertFalse(root.exists())
        with self.assertRaisesRegex(
            RunningJobAuthorityIntegrityError,
            "coordination lock",
        ):
            with authority.open_stable_index():
                self.fail("missing authority state must fail closed")
        self.assertFalse(root.exists())

    def test_public_snapshot_uses_existing_read_only_index_without_sidecars(self) -> None:
        authority = RunningJobAuthority(
            self.writer.root,
            foundation_root=REPO_ROOT,
        )
        index_payload = self.writer.index_path.read_bytes()
        lock_payload = authority.lock_path.read_bytes()
        entries = {path.name for path in self.writer.index_path.parent.iterdir()}
        with authority.open_stable_index() as (_control, index):
            self.assertIsNotNone(
                index.get("initiative-close", self.record_id)
            )
            self.assertFalse(hasattr(index, "put"))
            self.assertFalse(hasattr(index, "rebuild"))
        self.assertEqual(self.writer.index_path.read_bytes(), index_payload)
        self.assertEqual(authority.lock_path.read_bytes(), lock_payload)
        self.assertEqual(
            {path.name for path in self.writer.index_path.parent.iterdir()},
            entries,
        )

    def test_public_snapshot_rejects_legacy_schema_without_migration(self) -> None:
        authority = RunningJobAuthority(
            self.writer.root,
            foundation_root=REPO_ROOT,
        )
        with closing(sqlite3.connect(self.writer.index_path)) as connection:
            connection.execute("PRAGMA user_version = 0")
        payload = self.writer.index_path.read_bytes()
        entries = {path.name for path in self.writer.index_path.parent.iterdir()}
        with self.assertRaisesRegex(
            RunningJobAuthorityIntegrityError,
            "read-only local index",
        ):
            with authority.open_stable_index():
                self.fail("legacy projection must not be migrated by a reader")
        self.assertEqual(self.writer.index_path.read_bytes(), payload)
        self.assertEqual(
            {path.name for path in self.writer.index_path.parent.iterdir()},
            entries,
        )
        with closing(
            sqlite3.connect(
                self.writer.index_path.resolve().as_uri() + "?mode=ro",
                uri=True,
            )
        ) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)

    def test_public_snapshot_never_recreates_a_missing_index(self) -> None:
        authority = RunningJobAuthority(
            self.writer.root,
            foundation_root=REPO_ROOT,
        )
        self.writer.index_path.unlink()
        entries = {path.name for path in self.writer.index_path.parent.iterdir()}
        with self.assertRaisesRegex(
            RunningJobAuthorityIntegrityError,
            "read-only local index",
        ):
            with authority.open_stable_index():
                self.fail("reader must not reconstruct a missing projection")
        self.assertFalse(self.writer.index_path.exists())
        self.assertEqual(
            {path.name for path in self.writer.index_path.parent.iterdir()},
            entries,
        )

    def test_file_is_ascii(self) -> None:
        Path(__file__).read_text(encoding="ascii")


if __name__ == "__main__":
    unittest.main()
