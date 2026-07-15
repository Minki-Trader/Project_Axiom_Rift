from __future__ import annotations

from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
from threading import Event, Thread
import unittest

from axiom_rift.storage import (
    EvidenceStore,
    IndexRecord,
    LocalIndex,
    LocalIndexError,
    IndexIntegrityError,
    RecordCollisionError,
)


def record(
    number: int,
    *,
    subject: str = "subject-A",
    status: str = "open",
    fingerprint: str | None = None,
    stream: str | None = None,
    sequence: int | None = None,
) -> IndexRecord:
    return IndexRecord(
        kind="event",
        record_id=f"record-{number:05d}",
        subject=subject,
        status=status,
        fingerprint=fingerprint or f"fingerprint-{number:05d}",
        payload={"number": number, "nested": {"stable": True}},
        event_stream=stream,
        event_sequence=sequence,
    )


class LocalIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "index.sqlite3"

    def test_connection_uses_required_non_wal_settings(self) -> None:
        with LocalIndex(self.path) as index:
            self.assertEqual(
                index.settings(),
                {
                    "journal_mode": "delete",
                    "synchronous": 3,
                    "foreign_keys": 1,
                    "trusted_schema": 0,
                    "busy_timeout": 5_000,
                },
            )
            index.check_integrity()

    def test_durable_state_path_is_rejected_without_touching_bytes(self) -> None:
        state = Path(self.temporary.name) / "state"
        state.mkdir()
        protected = state / "index.sqlite"
        original = b"not a reconstructible projection"
        protected.write_bytes(original)

        with self.assertRaisesRegex(
            LocalIndexError,
            "local index belongs under local/",
        ):
            LocalIndex(protected)
        with self.assertRaisesRegex(
            LocalIndexError,
            "local index belongs under local/",
        ):
            LocalIndex.open_read_only(protected)

        self.assertEqual(protected.read_bytes(), original)
        self.assertFalse(Path(f"{protected}-journal").exists())
        self.assertFalse(Path(f"{protected}-wal").exists())
        self.assertFalse(Path(f"{protected}-shm").exists())

    def test_immutable_insert_is_idempotent_and_rejects_collision(self) -> None:
        original = record(1)
        with LocalIndex(self.path) as index:
            self.assertTrue(index.put(original))
            self.assertFalse(index.put(original))
            self.assertEqual(index.record_count(), 1)
            with self.assertRaises(RecordCollisionError):
                index.put(
                    IndexRecord(
                        kind=original.kind,
                        record_id=original.record_id,
                        subject=original.subject,
                        status="changed",
                        fingerprint=original.fingerprint,
                        payload=original.payload,
                    )
                )
            self.assertEqual(index.get(original.kind, original.record_id), original)

    def test_record_authority_and_event_positions_reject_boolean_integers(self) -> None:
        base = record(1)
        cases = (
            replace(
                base,
                event_stream="stream",
                event_sequence=True,
            ),
            replace(
                base,
                authority_sequence=True,
                authority_event_id="a" * 64,
                authority_offset=0,
            ),
            replace(
                base,
                authority_sequence=1,
                authority_event_id="a" * 64,
                authority_offset=True,
            ),
        )
        with LocalIndex(self.path) as index:
            for value in cases:
                with self.subTest(value=value), self.assertRaisesRegex(
                    ValueError, "integer|authority"
                ):
                    index.put(value)
            with self.assertRaisesRegex(ValueError, "non-negative integer"):
                index.event_record("stream", True)

    def test_indexed_lookups_and_event_head_projection(self) -> None:
        values = (
            record(1, subject="alpha", status="open", stream="stream-A", sequence=1),
            record(3, subject="alpha", status="closed", stream="stream-A", sequence=3),
            record(2, subject="alpha", status="open", stream="stream-A", sequence=2),
            record(4, subject="beta", status="open", fingerprint="shared"),
            record(5, subject="gamma", status="open", fingerprint="shared"),
        )
        with LocalIndex(self.path) as index:
            for value in values:
                self.assertTrue(index.put(value))
            head = index.event_head("stream-A")
            self.assertIsNotNone(head)
            assert head is not None
            self.assertEqual((head.sequence, head.record_id), (3, "record-00003"))
            self.assertEqual(
                [item.record_id for item in index.records_by_subject_status("alpha", "open")],
                ["record-00001", "record-00002"],
            )
            self.assertEqual(
                [item.record_id for item in index.records_by_fingerprint("shared")],
                ["record-00004", "record-00005"],
            )
            index.check_integrity()

    def test_subject_status_lookup_is_index_bounded_and_decodes_only_scope(
        self,
    ) -> None:
        validated: list[str] = []
        target_ids = [
            f"record-{number:05d}" for number in range(0, 4_000, 1_000)
        ]
        values = tuple(
            record(
                number,
                subject=(
                    "Mission:MIS-TARGET"
                    if number % 1_000 == 0
                    else f"Mission:MIS-{number % 97:04d}"
                ),
                status=("pending" if number % 1_000 == 0 else "open"),
            )
            for number in range(4_000)
        )
        with LocalIndex(
            self.path,
            authority_validator=lambda item: validated.append(item.record_id),
        ) as index:
            index.rebuild(values)
            validated.clear()

            selected = index.records_by_subject_status(
                "Mission:MIS-TARGET",
                "pending",
            )
            details = index.explain_hot_query(
                "records_by_subject_status",
                ("Mission:MIS-TARGET", "pending"),
            )

            self.assertEqual([item.record_id for item in selected], target_ids)
            self.assertEqual(validated, target_ids)
            self.assertEqual(
                index.hot_query_access_shape(
                    "records_by_subject_status",
                    ("Mission:MIS-TARGET", "pending"),
                ),
                ("SEARCH:records",),
            )
            self.assertTrue(
                any("ix_records_subject_status" in detail for detail in details)
            )
            self.assertFalse(
                any(detail.startswith("SCAN records") for detail in details)
            )
            self.assertEqual(
                index.read_only().records_by_subject_status(
                    "Mission:MIS-TARGET",
                    "pending",
                ),
                selected,
            )

    def test_kind_prefix_lookup_is_primary_key_bounded(self) -> None:
        validated: list[str] = []
        with LocalIndex(
            self.path,
            authority_validator=lambda item: validated.append(item.record_id),
        ) as index:
            index.rebuild(record(number) for number in range(2_000))
            validated.clear()

            selected = index.records_by_kind_prefix("event", "record-0001")

            self.assertEqual(
                [item.record_id for item in selected],
                [f"record-{number:05d}" for number in range(10, 20)],
            )
            self.assertEqual(validated, [item.record_id for item in selected])
            self.assertEqual(
                index.records_by_kind_prefix_access_shape(
                    "event",
                    "record-0001",
                ),
                ("SEARCH:records",),
            )
            with self.assertRaisesRegex(ValueError, "printable ASCII"):
                index.records_by_kind_prefix("event", "record-\x7f")

    def test_rebuild_is_atomic_and_reconstructs_heads(self) -> None:
        with LocalIndex(self.path) as index:
            index.put(record(99))
            rebuilt = (
                record(2, stream="stream-B", sequence=2),
                record(1, stream="stream-B", sequence=1),
                record(3, stream="stream-C", sequence=7),
            )
            self.assertEqual(index.rebuild(rebuilt), 3)
            self.assertIsNone(index.get("event", "record-00099"))
            self.assertEqual(index.event_head("stream-B").sequence, 2)  # type: ignore[union-attr]
            self.assertEqual(index.event_head("stream-C").sequence, 7)  # type: ignore[union-attr]
            index.check_integrity()

            colliding = (
                record(10, stream="collision", sequence=1),
                record(11, stream="collision", sequence=1),
            )
            with self.assertRaises(RecordCollisionError):
                index.rebuild(colliding)
            self.assertEqual(index.record_count(), 3)
            self.assertEqual(index.event_head("stream-B").sequence, 2)  # type: ignore[union-attr]

    def test_projection_row_and_event_head_tampering_fail_closed(self) -> None:
        with LocalIndex(self.path) as index:
            index.put(record(1, stream="source:fixture", sequence=1))
            index.put(record(2, stream="source:fixture", sequence=2))
            index._connection.execute(  # noqa: SLF001 - adversarial projection test
                "UPDATE records SET status = ? WHERE kind = ? AND record_id = ?",
                ("runtime_eligible", "event", "record-00002"),
            )
            with self.assertRaises(IndexIntegrityError):
                index.get("event", "record-00002")

        rollback_path = Path(self.temporary.name) / "head-rollback.sqlite3"
        with LocalIndex(rollback_path) as index:
            index.put(record(1, stream="source:fixture", sequence=1))
            index.put(record(2, stream="source:fixture", sequence=2))
            index._connection.execute(  # noqa: SLF001 - adversarial projection test
                "UPDATE event_heads SET sequence = ?, record_id = ?, fingerprint = ? "
                "WHERE stream = ?",
                (1, "record-00001", "fingerprint-00001", "source:fixture"),
            )
            with self.assertRaises(IndexIntegrityError):
                index.event_head("source:fixture")

    def test_count_by_kind_is_keyed_without_authority_row_decodes(self) -> None:
        validated: list[str] = []
        with LocalIndex(
            self.path,
            authority_validator=lambda item: validated.append(item.record_id),
        ) as index:
            index.rebuild(record(number) for number in range(2_000))
            validated.clear()
            self.assertEqual(index.count_by_kind("event"), 2_000)
            self.assertEqual(index.count_by_kind("absent"), 0)
            self.assertEqual(validated, [])
            index._connection.execute(  # noqa: SLF001 - adversarial view test
                "UPDATE record_kind_stats SET record_count = ? WHERE kind = ?",
                (1_999, "event"),
            )
            with self.assertRaisesRegex(IndexIntegrityError, "count projection"):
                index.count_by_kind("event")

    def test_authority_prefix_count_uses_covering_index_without_decodes(self) -> None:
        validated: list[str] = []
        trials = tuple(
            IndexRecord(
                kind="trial",
                record_id=f"executable:{number:064x}",
                subject="Batch:fixture",
                status="evaluated",
                fingerprint=f"{number:064x}",
                payload={"ordinal": number},
                authority_sequence=number + 10,
                authority_event_id=f"{number + 10:064x}",
                authority_offset=number + 100,
            )
            for number in range(2_000)
        )
        with LocalIndex(
            self.path,
            authority_validator=lambda item: validated.append(item.record_id),
        ) as index:
            index.rebuild(trials)
            validated.clear()

            self.assertEqual(
                index.count_by_kind_before_authority_sequence("trial", 1_010),
                1_000,
            )
            details = index.count_by_kind_before_authority_sequence_access_shape(
                "trial",
                1_010,
            )

            self.assertEqual(validated, [])
            self.assertTrue(
                any("ix_records_kind_authority_sequence" in item for item in details)
            )
            self.assertFalse(any(item.startswith("SCAN records") for item in details))
            with self.assertRaisesRegex(ValueError, "positive integer"):
                index.count_by_kind_before_authority_sequence("trial", 0)

    def test_exact_authority_event_kind_lookup_is_index_bounded(self) -> None:
        validated: list[str] = []
        operations = tuple(
            IndexRecord(
                kind="operation",
                record_id=f"operation-{number:05d}",
                subject="Mission:active",
                status="success",
                fingerprint=f"{number:064x}",
                payload={"event_kind": "fixture", "result": {"number": number}},
                authority_sequence=number + 1,
                authority_event_id=f"{number + 1:064x}",
                authority_offset=number + 100,
            )
            for number in range(2_000)
        )
        with LocalIndex(
            self.path,
            authority_validator=lambda item: validated.append(item.record_id),
        ) as index:
            index.rebuild(operations)
            validated.clear()

            selected = index.records_by_kind_at_authority_sequence(
                "operation",
                1_001,
            )
            details = index.records_by_kind_at_authority_sequence_access_shape(
                "operation",
                1_001,
            )

            self.assertEqual(
                [item.record_id for item in selected],
                ["operation-01000"],
            )
            self.assertEqual(validated, ["operation-01000"])
            self.assertTrue(
                any("ix_records_kind_authority_sequence" in item for item in details)
            )
            self.assertFalse(any(item.startswith("SCAN records") for item in details))
            self.assertEqual(
                index.read_only().records_by_kind_at_authority_sequence(
                    "operation",
                    1_001,
                ),
                selected,
            )
            with self.assertRaisesRegex(ValueError, "positive integer"):
                index.records_by_kind_at_authority_sequence("operation", 0)

    def test_read_only_view_exposes_no_mutation_capability(self) -> None:
        with LocalIndex(self.path) as index:
            index.put(record(1))
            view = index.read_only()
            self.assertFalse(index._connection.in_transaction)  # noqa: SLF001
            self.assertEqual(view.get("event", "record-00001"), record(1))
            self.assertFalse(index._connection.in_transaction)  # noqa: SLF001
            self.assertEqual(view.path, self.path)
            self.assertFalse(hasattr(view, "put"))
            self.assertFalse(hasattr(view, "rebuild"))
            self.assertTrue(index.put(record(2)))
            self.assertEqual(view.get("event", "record-00002"), record(2))

    def test_true_read_only_open_never_creates_or_migrates_projection(self) -> None:
        with LocalIndex(self.path) as index:
            index.put(record(1))
        payload_before = self.path.read_bytes()
        entries_before = {path.name for path in self.path.parent.iterdir()}

        with LocalIndex.open_read_only(self.path) as view:
            self.assertEqual(view.get("event", "record-00001"), record(1))
            self.assertEqual(view.path, self.path)
            self.assertEqual(view.record_count(), 1)
            self.assertFalse(hasattr(view, "put"))
            self.assertFalse(hasattr(view, "put_many"))
            self.assertFalse(hasattr(view, "rebuild"))

        self.assertEqual(self.path.read_bytes(), payload_before)
        self.assertEqual(
            {path.name for path in self.path.parent.iterdir()},
            entries_before,
        )

        missing = self.path.parent / "absent" / "index.sqlite3"
        with self.assertRaisesRegex(LocalIndexError, "must already exist"):
            LocalIndex.open_read_only(missing)
        self.assertFalse(missing.parent.exists())

        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("PRAGMA user_version = 0")
        legacy_before = self.path.read_bytes()
        entries_before = {path.name for path in self.path.parent.iterdir()}
        with self.assertRaisesRegex(
            LocalIndexError,
            "explicit local-index materialization",
        ):
            LocalIndex.open_read_only(self.path)
        self.assertEqual(self.path.read_bytes(), legacy_before)
        self.assertEqual(
            {path.name for path in self.path.parent.iterdir()},
            entries_before,
        )
        with closing(
            sqlite3.connect(
                self.path.resolve().as_uri() + "?mode=ro",
                uri=True,
            )
        ) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)

    def test_owned_read_only_view_pins_one_snapshot_across_queries(self) -> None:
        with LocalIndex(self.path) as index:
            index.put(record(1))

        writer_ready = Event()
        start_write = Event()
        commit_attempted = Event()
        writer_finished = Event()
        writer_errors: list[BaseException] = []

        def write_second_record() -> None:
            try:
                with LocalIndex(self.path) as writer:
                    writer._connection.set_trace_callback(  # noqa: SLF001
                        lambda statement: (
                            commit_attempted.set()
                            if statement.strip().upper() == "COMMIT"
                            else None
                        )
                    )
                    writer_ready.set()
                    if not start_write.wait(5):
                        raise AssertionError("snapshot test writer was not released")
                    writer.put(record(2))
            except BaseException as exc:  # pragma: no cover - asserted below
                writer_errors.append(exc)
            finally:
                writer_finished.set()

        thread = Thread(target=write_second_record, daemon=True)
        thread.start()
        self.assertTrue(writer_ready.wait(5))
        try:
            with LocalIndex.open_read_only(self.path) as view:
                self.assertEqual(view.record_count(), 1)
                self.assertIsNone(view.get("event", "record-00002"))
                start_write.set()
                self.assertTrue(commit_attempted.wait(5))

                self.assertFalse(writer_finished.wait(0.1))
                self.assertEqual(view.record_count(), 1)
                self.assertIsNone(view.get("event", "record-00002"))
        finally:
            start_write.set()
            thread.join(5)

        self.assertFalse(thread.is_alive())
        self.assertEqual(writer_errors, [])
        with LocalIndex.open_read_only(self.path) as view:
            self.assertEqual(view.record_count(), 2)
            self.assertEqual(view.get("event", "record-00002"), record(2))

    def test_index_creation_does_not_traverse_a_linked_parent(self) -> None:
        outside = self.path.parent / "outside"
        outside.mkdir()
        linked = self.path.parent / "linked"
        try:
            linked.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"directory symbolic links unavailable: {exc}")
        target = linked / "created" / "index.sqlite3"
        with self.assertRaisesRegex(LocalIndexError, "directory boundary"):
            LocalIndex(target)
        self.assertFalse((outside / "created").exists())

    def test_existing_projection_migrates_kind_counts_once(self) -> None:
        with LocalIndex(self.path) as index:
            index.put_many((record(1), record(2)))
            index._connection.execute(  # noqa: SLF001 - legacy schema fixture
                "DELETE FROM record_kind_stats"
            )
            index._connection.execute(  # noqa: SLF001 - legacy schema fixture
                "UPDATE projection_stats SET projection_valid = 1"
            )
            index._connection.execute(  # noqa: SLF001 - legacy schema fixture
                "PRAGMA user_version = 0"
            )
        with LocalIndex(self.path) as migrated:
            self.assertEqual(migrated.count_by_kind("event"), 2)
            self.assertEqual(
                migrated._connection.execute(  # noqa: SLF001
                    "PRAGMA user_version"
                ).fetchone()[0],
                3,
            )

    def test_event_head_delete_or_same_count_replacement_invalidates_projection(self) -> None:
        cases = ("delete", "replace", "tamper")
        for case in cases:
            with self.subTest(case=case):
                path = Path(self.temporary.name) / f"head-{case}.sqlite3"
                with LocalIndex(path) as index:
                    first = record(1, stream="source:fixture", sequence=1)
                    second = record(2, stream="source:fixture", sequence=2)
                    index.put_many((first, second))
                    record_count = index.record_count()

                    if case == "delete":
                        index._connection.execute(  # noqa: SLF001 - adversarial projection test
                            "DELETE FROM event_heads WHERE stream = ?",
                            ("source:fixture",),
                        )
                    elif case == "replace":
                        index._connection.execute(  # noqa: SLF001 - adversarial projection test
                            "DELETE FROM event_heads WHERE stream = ?",
                            ("source:fixture",),
                        )
                        index._connection.execute(  # noqa: SLF001 - adversarial projection test
                            "INSERT INTO event_heads("
                            "stream, sequence, record_kind, record_id, fingerprint"
                            ") VALUES (?, ?, ?, ?, ?)",
                            (
                                "source:fixture",
                                2,
                                second.kind,
                                second.record_id,
                                second.fingerprint,
                            ),
                        )
                    else:
                        index._connection.execute(  # noqa: SLF001 - adversarial projection test
                            "UPDATE event_heads SET fingerprint = ? WHERE stream = ?",
                            ("unauthorized", "source:fixture"),
                        )

                    self.assertEqual(index.record_count(), record_count)
                    self.assertEqual(index.projection_guard()[1], False)
                    with self.assertRaises(IndexIntegrityError):
                        index.check_integrity()
                    with self.assertRaises(IndexIntegrityError):
                        index.projected_digest((record(3),))
                    self.assertTrue(index.put(record(3)))
                    self.assertEqual(index.projection_guard()[1], False)

    def test_hot_query_access_shape_is_history_size_invariant(self) -> None:
        small_path = Path(self.temporary.name) / "small.sqlite3"
        large_path = Path(self.temporary.name) / "large.sqlite3"
        with LocalIndex(small_path) as small, LocalIndex(large_path) as large:
            small.rebuild(
                (
                    record(
                        number,
                        subject="target" if number == 1 else "other",
                        status="open",
                        stream="small-stream",
                        sequence=number,
                    )
                    for number in range(4)
                )
            )
            large.rebuild(
                (
                    record(
                        number,
                        subject="target" if number == 1 else f"subject-{number % 31}",
                        status="open" if number % 2 else "closed",
                        stream="large-stream",
                        sequence=number,
                    )
                    for number in range(2_000)
                )
            )

            parameters = {
                "record_by_key": ("event", "record-00001"),
                "event_head_by_stream": ("small-stream",),
                "latest_event_record_by_stream": ("small-stream",),
                "event_record_by_position": ("small-stream", 1),
                "projection_record_count": (1,),
                "record_count_by_kind": ("event",),
            }
            large_parameters = dict(parameters)
            large_parameters["event_head_by_stream"] = ("large-stream",)
            large_parameters["latest_event_record_by_stream"] = ("large-stream",)
            large_parameters["event_record_by_position"] = ("large-stream", 1)
            small_shapes = {
                name: small.hot_query_access_shape(name, parameters[name])
                for name in small.hot_query_names()
            }
            large_shapes = {
                name: large.hot_query_access_shape(name, large_parameters[name])
                for name in large.hot_query_names()
            }
            self.assertEqual(small_shapes, large_shapes)
            self.assertEqual(small_shapes, small.check_hot_queries())
            self.assertEqual(
                small.current_lookup_row_bounds(),
                {
                    "record_by_key": 1,
                    "event_head_by_stream": 1,
                    "latest_event_record_by_stream": 1,
                    "event_record_by_position": 1,
                    "projection_record_count": 1,
                    "record_count_by_kind": 1,
                },
            )
            small_store = EvidenceStore(Path(self.temporary.name) / "small-evidence")
            large_store = EvidenceStore(Path(self.temporary.name) / "large-evidence")
            identities = (
                small_store.finalize(b"current manifest artifact one").sha256,
                small_store.finalize(b"current manifest artifact two").sha256,
            )
            for content in (
                b"current manifest artifact one",
                b"current manifest artifact two",
            ):
                large_store.finalize(content)
            _, small_manifest_trace = small_store.verify_manifest(identities)
            _, large_manifest_trace = large_store.verify_manifest(identities)
            self.assertEqual(small_manifest_trace, large_manifest_trace)
            self.assertEqual(small_manifest_trace.observed_path_count, 2)
            self.assertEqual(small_manifest_trace.directory_enumerations, 0)
            small_traces = tuple(
                small.trace_current_lookup(
                    name,
                    parameters[name],
                    manifest_paths=small_manifest_trace.relative_paths,
                )
                for name in small.hot_query_names()
            )
            large_traces = tuple(
                large.trace_current_lookup(
                    name,
                    large_parameters[name],
                    manifest_paths=large_manifest_trace.relative_paths,
                )
                for name in large.hot_query_names()
            )
            self.assertEqual(
                tuple(
                    (
                        trace.query_name,
                        trace.access_shape,
                        trace.uniqueness_basis,
                        trace.visited_row_upper_bound,
                        trace.returned_row_count,
                        trace.manifest_paths,
                    )
                    for trace in small_traces
                ),
                tuple(
                    (
                        trace.query_name,
                        trace.access_shape,
                        trace.uniqueness_basis,
                        trace.visited_row_upper_bound,
                        trace.returned_row_count,
                        trace.manifest_paths,
                    )
                    for trace in large_traces
                ),
            )
            self.assertTrue(
                all(trace.visited_row_upper_bound == 1 for trace in small_traces)
            )
            self.assertTrue(
                all(
                    any(part.startswith("SEARCH:") for part in shape)
                    for shape in small_shapes.values()
                )
            )


if __name__ == "__main__":
    unittest.main()
