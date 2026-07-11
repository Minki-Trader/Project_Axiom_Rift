from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from axiom_rift.storage import (
    EvidenceStore,
    IndexRecord,
    LocalIndex,
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
