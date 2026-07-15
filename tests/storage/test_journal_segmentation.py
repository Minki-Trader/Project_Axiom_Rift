from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import axiom_rift.storage.atomic_file as atomic_file_module
from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
from axiom_rift.storage.journal import (
    DurableJournal,
    JournalError,
    JournalHead,
    JournalIntegrityError,
    TornJournalError,
    _atomic_write,
    _base,
    _issue_journal_write_capability,
    _render_manifest,
)


class JournalSegmentationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "records" / "journal.jsonl"
        self.journal = DurableJournal(self.path)
        self.capability = _issue_journal_write_capability()

    def test_read_side_construction_does_not_create_missing_journal_parent(self) -> None:
        path = self.root / "absent" / "records" / "journal.jsonl"
        journal = DurableJournal(path, create_parent=False)
        self.assertFalse(path.parent.exists())
        self.assertEqual(journal.tail(), (JournalHead(0, None), None))
        self.assertFalse(path.parent.exists())
        for value in (0, 1, "false"):
            with self.subTest(create_parent=value), self.assertRaisesRegex(
                ValueError, "must be boolean"
            ):
                DurableJournal(path, create_parent=value)  # type: ignore[arg-type]

    def test_journal_creation_does_not_traverse_a_linked_parent(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        linked = self.root / "linked"
        try:
            linked.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"directory symbolic links unavailable: {exc}")
        path = linked / "created" / "records" / "journal.jsonl"
        with self.assertRaisesRegex(JournalError, "directory boundary"):
            DurableJournal(path)
        self.assertFalse((outside / "created").exists())

    def test_atomic_write_ignores_predictable_symbolic_link_residue(self) -> None:
        target = self.path.parent / "authority.json"
        outside = self.root / "outside.json"
        outside.write_bytes(b"outside-must-not-change")
        residue = target.with_name(f".{target.name}.tmp")
        try:
            residue.symlink_to(outside)
        except OSError as exc:
            self.skipTest(f"symbolic links unavailable: {exc}")

        _atomic_write(target, b"published")

        self.assertEqual(target.read_bytes(), b"published")
        self.assertEqual(outside.read_bytes(), b"outside-must-not-change")
        self.assertTrue(residue.is_symlink())

    def test_atomic_write_never_publishes_or_cleans_a_foreign_temporary(self) -> None:
        target = self.path.parent / "authority.json"
        foreign = self.root / "foreign.json"
        foreign.write_bytes(b"foreign-must-not-change")
        original_directory_identity = atomic_file_module._directory_identity
        captured: dict[str, Path] = {}
        calls = 0

        def replace_before_publish(parent: Path) -> tuple[int, int]:
            nonlocal calls
            identity = original_directory_identity(parent)
            calls += 1
            if calls == 2:
                candidates = tuple(parent.glob(".authority.json.*.tmp"))
                self.assertEqual(len(candidates), 1)
                temporary = candidates[0]
                temporary.unlink()
                os.link(foreign, temporary)
                captured["temporary"] = temporary
            return identity

        with (
            patch.object(
                atomic_file_module,
                "_directory_identity",
                side_effect=replace_before_publish,
            ),
            self.assertRaisesRegex(JournalError, "atomic write boundary"),
        ):
            _atomic_write(target, b"must-not-publish")

        replacement = captured["temporary"]
        self.assertFalse(target.exists())
        self.assertEqual(foreign.read_bytes(), b"foreign-must-not-change")
        self.assertEqual(replacement.read_bytes(), b"foreign-must-not-change")

    def append(
        self,
        journal: DurableJournal | None = None,
        *,
        event_kind: str = "fixture_recorded",
        operation_id: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        target = self.journal if journal is None else journal
        head = target.tail()[0]
        return target._append_authorized(
            capability=self.capability,
            expected_head=head,
            event_kind=event_kind,
            operation_id=operation_id or f"fixture-{head.sequence + 1}",
            subject="Fixture:Journal",
            occurred_at_utc="2026-07-13T00:00:00Z",
            payload={} if payload is None else payload,
            control={"fixture_sequence": head.sequence + 1},
            index_records=[],
            index_record_count=head.sequence + 1,
            index_projection_digest=f"{head.sequence + 1:064x}",
        )

    def migration_event(self, journal: DurableJournal | None = None) -> dict[str, object]:
        target = self.journal if journal is None else journal
        content = target.path.read_bytes()
        events = target.read_all()
        payload: dict[str, object] = {
            "schema": "journal_storage_migration.v1",
            "boundary": "active_stable",
            "reason": "test exact segmented storage",
            "legacy_path": "records/journal.jsonl",
            "manifest_path": "records/journal/manifest.json",
            "sealed_segment_id": "000001",
            "sealed_segment_path": "records/journal/journal-000001.jsonl",
            "seal_path": "records/journal/journal-000001.seal.json",
            "active_segment_id": "000002",
            "active_segment_path": "records/journal/journal-000002.jsonl",
            "pre_migration": {
                "byte_length": len(content),
                "sha256": __import__("hashlib").sha256(content).hexdigest(),
                "first_sequence": events[0]["sequence"],
                "last_sequence": events[-1]["sequence"],
                "first_event_id": events[0]["event_id"],
                "last_event_id": events[-1]["event_id"],
            },
            "trial_delta": 0,
            "holdout_delta": 0,
            "candidate_delta": 0,
            "claim_delta": 0,
            "recovery_action": "StateWriter.recover",
        }
        return self.append(
            target,
            event_kind="journal_storage_migrated",
            operation_id="migrate-journal-storage",
            payload=payload,
        )

    def migrate(self, journal: DurableJournal | None = None) -> dict[str, object]:
        target = self.journal if journal is None else journal
        event = self.migration_event(target)
        target.materialize_legacy_migration(event)
        return event

    def test_exact_legacy_prefix_event_ids_and_offsets_survive_migration(self) -> None:
        for _ in range(3):
            self.append()
        prefix = self.path.read_bytes()
        original = self.journal.read_all()
        migration = self.migrate()

        sealed = self.root / "records" / "journal" / "journal-000001.jsonl"
        active = self.root / "records" / "journal" / "journal-000002.jsonl"
        self.assertFalse(self.path.exists())
        self.assertTrue(sealed.read_bytes().startswith(prefix))
        self.assertEqual(active.read_bytes(), b"")
        observed = self.journal.read_all()
        self.assertEqual(observed[: len(original)], original)
        self.assertEqual(
            [event["journal_offset"] for event in observed[: len(original)]],
            [event["journal_offset"] for event in original],
        )
        self.assertEqual(self.journal.tail()[0], JournalHead(4, migration["event_id"]))

    def test_segmented_tail_uses_sealed_boundary_when_active_is_empty(self) -> None:
        for _ in range(3):
            self.append()
        migration = self.migrate()
        fresh = DurableJournal(self.path)
        with patch.object(
            fresh,
            "_snapshot",
            side_effect=AssertionError("segmented tail performed a full replay"),
        ):
            head, tail = fresh.tail()
        self.assertEqual(head, JournalHead(4, migration["event_id"]))
        self.assertEqual(tail, migration)

    def test_segmented_tail_reads_only_bounded_segment_ranges(self) -> None:
        for _ in range(32):
            self.append()
        self.migrate()
        active_tail: dict[str, object] | None = None
        for _ in range(32):
            active_tail = self.append()
        assert active_tail is not None

        fresh = DurableJournal(self.path)
        fresh.MAX_EVENT_BYTES = 4_096
        directory = self.root / "records" / "journal"
        sources = {
            path.name: path.stat().st_size
            for path in (
                directory / "journal-000001.jsonl",
                directory / "journal-000002.jsonl",
            )
        }
        for size in sources.values():
            self.assertGreater(size, 2 * (fresh.MAX_EVENT_BYTES + 2))

        original_open = Path.open
        requested: list[tuple[str, str, int, int]] = []

        class CountingHandle:
            def __init__(self, path: Path, handle: object) -> None:
                self.path = path
                self.handle = handle

            def __enter__(self) -> "CountingHandle":
                self.handle.__enter__()  # type: ignore[attr-defined]
                return self

            def __exit__(self, *args: object) -> object:
                return self.handle.__exit__(*args)  # type: ignore[attr-defined]

            def __getattr__(self, name: str) -> object:
                return getattr(self.handle, name)

            def read(self, size: int = -1) -> bytes:
                content = self.handle.read(size)  # type: ignore[attr-defined]
                requested.append((self.path.name, "read", size, len(content)))
                return content

            def readline(self, size: int = -1) -> bytes:
                content = self.handle.readline(size)  # type: ignore[attr-defined]
                requested.append((self.path.name, "readline", size, len(content)))
                return content

        def counted_open(path: Path, *args: object, **kwargs: object) -> object:
            handle = original_open(path, *args, **kwargs)  # type: ignore[arg-type]
            mode = args[0] if args else kwargs.get("mode", "r")
            if mode == "rb" and path.suffix == ".jsonl":
                return CountingHandle(path, handle)
            return handle

        with (
            patch.object(
                fresh,
                "_snapshot",
                side_effect=AssertionError("segmented tail performed a full replay"),
            ),
            patch.object(Path, "open", new=counted_open),
        ):
            head, observed = fresh.tail()

        self.assertEqual(
            head, JournalHead(active_tail["sequence"], active_tail["event_id"])
        )
        self.assertEqual(observed, active_tail)
        self.assertEqual({item[0] for item in requested}, set(sources))
        for name, _method, requested_size, actual_size in requested:
            self.assertGreater(requested_size, 0)
            self.assertLessEqual(requested_size, fresh.MAX_EVENT_BYTES + 2)
            self.assertLessEqual(actual_size, requested_size)
        for name, source_size in sources.items():
            self.assertLess(
                sum(item[3] for item in requested if item[0] == name),
                source_size,
            )

    def test_segmented_tail_reads_a_large_record_across_bounded_chunks(self) -> None:
        self.append()
        self.migrate()
        self.append()
        expected = self.append(payload={"large": "x" * 100_000})
        fresh = DurableJournal(self.path)
        with patch.object(
            fresh,
            "_snapshot",
            side_effect=AssertionError("segmented tail performed a full replay"),
        ):
            head, observed = fresh.tail()
        self.assertEqual(head, JournalHead(expected["sequence"], expected["event_id"]))
        self.assertEqual(observed, expected)

    def test_segmented_append_uses_global_offset_and_cross_segment_lookup(self) -> None:
        first = self.append()
        self.migrate()
        sealed_size = (
            self.root / "records" / "journal" / "journal-000001.jsonl"
        ).stat().st_size
        appended = self.append()
        self.assertEqual(appended["journal_offset"], sealed_size)
        self.assertEqual(
            self.journal.read_event_at(
                offset=first["journal_offset"],
                expected_sequence=first["sequence"],
                expected_event_id=first["event_id"],
            ),
            first,
        )
        self.assertEqual(
            self.journal.read_event_at(
                offset=appended["journal_offset"],
                expected_sequence=appended["sequence"],
                expected_event_id=appended["event_id"],
            ),
            appended,
        )

    def test_sealed_lookup_verification_count_is_history_size_invariant(self) -> None:
        verification_counts: list[int] = []
        for event_count in (3, 250):
            with self.subTest(event_count=event_count), TemporaryDirectory() as temporary:
                journal = DurableJournal(
                    Path(temporary) / "records" / "journal.jsonl"
                )
                events = [self.append(journal) for _ in range(event_count)]
                self.migrate(journal)
                with patch.object(
                    journal,
                    "_read_and_verify_sealed_segment",
                    wraps=journal._read_and_verify_sealed_segment,
                ) as verification:
                    for event in (*events, *reversed(events)):
                        self.assertEqual(
                            journal.read_event_at(
                                offset=event["journal_offset"],
                                expected_sequence=event["sequence"],
                                expected_event_id=event["event_id"],
                            ),
                            event,
                        )
                verification_counts.append(verification.call_count)
        self.assertEqual(verification_counts, [1, 1])

    def test_sealed_cache_drift_replacement_and_corruption_revalidate(self) -> None:
        cases = ("content", "size", "seal", "replacement", "cache")
        for case in cases:
            with self.subTest(case=case), TemporaryDirectory() as temporary:
                root = Path(temporary)
                journal = DurableJournal(root / "records" / "journal.jsonl")
                event = self.append(journal)
                self.migrate(journal)
                directory = root / "records" / "journal"
                segment = directory / "journal-000001.jsonl"
                seal = directory / "journal-000001.seal.json"
                with patch.object(
                    journal,
                    "_read_and_verify_sealed_segment",
                    wraps=journal._read_and_verify_sealed_segment,
                ) as verification:
                    journal.read_event_at(
                        offset=event["journal_offset"],
                        expected_sequence=event["sequence"],
                        expected_event_id=event["event_id"],
                    )
                    if case == "content":
                        content = bytearray(segment.read_bytes())
                        content[10] = ord("z") if content[10] != ord("z") else ord("y")
                        segment.write_bytes(content)
                    elif case == "size":
                        segment.write_bytes(segment.read_bytes()[:-1])
                    elif case == "seal":
                        seal.write_bytes(seal.read_bytes()[:-1])
                    elif case == "replacement":
                        replacement = directory / "replacement.jsonl"
                        replacement.write_bytes(segment.read_bytes())
                        os.replace(replacement, segment)
                    else:
                        journal._sealed_segment_cache[  # noqa: SLF001
                            "records/journal/journal-000001.jsonl"
                        ] = object()  # type: ignore[assignment]
                    if case in {"replacement", "cache"}:
                        self.assertEqual(
                            journal.read_event_at(
                                offset=event["journal_offset"],
                                expected_sequence=event["sequence"],
                                expected_event_id=event["event_id"],
                            ),
                            event,
                        )
                    else:
                        with self.assertRaises(JournalIntegrityError):
                            journal.read_event_at(
                                offset=event["journal_offset"],
                                expected_sequence=event["sequence"],
                                expected_event_id=event["event_id"],
                            )
                self.assertEqual(verification.call_count, 2)

    def test_rotation_reuses_old_seal_and_verifies_only_new_seal(self) -> None:
        first = self.append()
        self.migrate()
        with patch.object(
            self.journal,
            "_read_and_verify_sealed_segment",
            wraps=self.journal._read_and_verify_sealed_segment,
        ) as verification:
            self.journal.read_event_at(
                offset=first["journal_offset"],
                expected_sequence=first["sequence"],
                expected_event_id=first["event_id"],
            )
            with patch.object(DurableJournal, "MAX_SEGMENT_EVENTS", 1):
                second = self.append()
                self.append()
            self.journal.read_event_at(
                offset=first["journal_offset"],
                expected_sequence=first["sequence"],
                expected_event_id=first["event_id"],
            )
            self.journal.read_event_at(
                offset=second["journal_offset"],
                expected_sequence=second["sequence"],
                expected_event_id=second["event_id"],
            )
        self.assertEqual(verification.call_count, 2)

    def test_event_count_rotation_keeps_whole_event_and_chain(self) -> None:
        self.append()
        self.migrate()
        with patch.object(DurableJournal, "MAX_SEGMENT_EVENTS", 2):
            second_segment_events = [self.append(), self.append()]
            rotated_event = self.append(payload={"large": "x" * 4096})
        manifest = json.loads(
            (self.root / "records" / "journal" / "manifest.json").read_bytes()
        )
        self.assertEqual(len(manifest["sealed_segments"]), 2)
        self.assertEqual(manifest["active_segment"]["id"], "000003")
        second = self.root / "records" / "journal" / "journal-000002.jsonl"
        third = self.root / "records" / "journal" / "journal-000003.jsonl"
        self.assertEqual(len(second.read_bytes().splitlines()), 2)
        self.assertEqual(len(third.read_bytes().splitlines()), 1)
        self.assertEqual(
            rotated_event["previous_event_id"],
            second_segment_events[-1]["event_id"],
        )
        self.assertEqual(self.journal.read_all()[-1], rotated_event)

    def test_byte_threshold_rotates_before_oversized_append(self) -> None:
        self.append()
        self.migrate()
        active = self.root / "records" / "journal" / "journal-000002.jsonl"
        first_active = self.append(payload={"small": "x" * 100})
        with patch.object(DurableJournal, "MAX_SEGMENT_BYTES", 2_000):
            event = self.append(payload={"large": "x" * 1500})
        self.assertEqual(len(active.read_bytes().splitlines()), 1)
        self.assertEqual(
            json.loads(active.read_bytes().splitlines()[0]), first_active
        )
        new_active = self.root / "records" / "journal" / "journal-000003.jsonl"
        self.assertEqual(len(new_active.read_bytes().splitlines()), 1)
        self.assertEqual(self.journal.read_all()[-1], event)

    def test_tampered_sealed_segment_fails_closed(self) -> None:
        self.append()
        self.migrate()
        sealed = self.root / "records" / "journal" / "journal-000001.jsonl"
        content = bytearray(sealed.read_bytes())
        content[10] = ord("z") if content[10] != ord("z") else ord("y")
        sealed.write_bytes(content)
        with self.assertRaisesRegex(JournalIntegrityError, "hash|differs"):
            self.journal.read_all()

    def test_unreferenced_segment_fails_closed(self) -> None:
        self.append()
        self.migrate()
        orphan = self.root / "records" / "journal" / "journal-999999.jsonl"
        orphan.write_bytes(b"")
        with self.assertRaisesRegex(JournalIntegrityError, "unreferenced"):
            DurableJournal(self.path).tail()
        with self.assertRaisesRegex(JournalIntegrityError, "unreferenced"):
            self.journal.read_all()

    def test_fast_tail_rejects_boolean_byte_offset(self) -> None:
        event = self.append()
        event["journal_offset"] = False
        event["event_id"] = canonical_digest(
            domain="journal-event", payload=_base(event)
        )
        self.path.write_bytes(canonical_bytes(event) + b"\n")

        with self.assertRaisesRegex(
            JournalIntegrityError, "byte offset mismatch"
        ):
            DurableJournal(self.path).tail()

    def test_full_event_validation_rejects_boolean_authority_integers(self) -> None:
        event = self.append()
        for field in ("sequence", "index_record_count", "journal_offset"):
            with self.subTest(field=field):
                malformed = dict(event)
                malformed[field] = True
                malformed["event_id"] = canonical_digest(
                    domain="journal-event",
                    payload=_base(malformed),
                )
                with self.assertRaises(JournalIntegrityError):
                    DurableJournal.validate_event(
                        malformed,
                        expected_sequence=1,
                        expected_previous=None,
                        expected_offset=0,
                    )
        with self.assertRaisesRegex(JournalIntegrityError, "sequence mismatch"):
            DurableJournal.validate_event(
                event,
                expected_sequence=True,  # type: ignore[arg-type]
                expected_previous=None,
                expected_offset=0,
            )

    def test_manifest_digest_path_and_coordinate_damage_fail_closed(self) -> None:
        corruptions = ("digest", "path", "offset", "sequence", "id")
        for corruption in corruptions:
            with self.subTest(corruption=corruption):
                with TemporaryDirectory() as temporary:
                    path = Path(temporary) / "records" / "journal.jsonl"
                    journal = DurableJournal(path)
                    self.append(journal)
                    self.migrate(journal)
                    manifest_path = (
                        Path(temporary) / "records" / "journal" / "manifest.json"
                    )
                    manifest = json.loads(manifest_path.read_bytes())
                    if corruption == "digest":
                        manifest["manifest_digest"] = "0" * 64
                        manifest_path.write_bytes(canonical_bytes(manifest))
                    else:
                        active = dict(manifest["active_segment"])
                        if corruption == "path":
                            active["path"] = "records/journal/../escape.jsonl"
                        elif corruption == "offset":
                            active["start_offset"] += 1
                        elif corruption == "sequence":
                            active["first_sequence"] += 1
                        else:
                            active["id"] = "000001"
                        manifest_path.write_bytes(
                            _render_manifest(
                                sealed_segments=manifest["sealed_segments"],
                                active_segment=active,
                            )
                        )
                    with self.assertRaises(JournalIntegrityError):
                        journal.read_all()

    def test_modified_or_truncated_seal_fails_closed(self) -> None:
        for corruption in ("seal", "segment"):
            with self.subTest(corruption=corruption):
                with TemporaryDirectory() as temporary:
                    path = Path(temporary) / "records" / "journal.jsonl"
                    journal = DurableJournal(path)
                    self.append(journal)
                    self.migrate(journal)
                    directory = Path(temporary) / "records" / "journal"
                    target = (
                        directory / "journal-000001.seal.json"
                        if corruption == "seal"
                        else directory / "journal-000001.jsonl"
                    )
                    target.write_bytes(target.read_bytes()[:-1])
                    with self.assertRaises(JournalIntegrityError):
                        journal.read_all()

    def test_torn_active_segment_fails_closed(self) -> None:
        self.append()
        self.migrate()
        self.append()
        active = self.root / "records" / "journal" / "journal-000002.jsonl"
        active.write_bytes(active.read_bytes()[:-1])
        with self.assertRaises(TornJournalError):
            DurableJournal(self.path).tail()
        with self.assertRaises(TornJournalError):
            self.journal.read_all()

    def test_segmented_tail_rejects_damaged_first_active_boundary(self) -> None:
        self.append()
        self.migrate()
        self.append()
        expected_tail = self.append()
        active = self.root / "records" / "journal" / "journal-000002.jsonl"
        framed = active.read_bytes().splitlines(keepends=True)
        first = json.loads(framed[0][:-1])
        first["previous_event_id"] = "0" * 64
        replacement = canonical_bytes(first) + b"\n"
        self.assertEqual(len(replacement), len(framed[0]))
        active.write_bytes(replacement + b"".join(framed[1:]))

        fresh = DurableJournal(self.path)
        with (
            patch.object(
                fresh,
                "_snapshot",
                side_effect=AssertionError("segmented tail performed a full replay"),
            ),
            self.assertRaisesRegex(JournalIntegrityError, "previous-event"),
        ):
            fresh.tail()
        self.assertEqual(json.loads(framed[-1]), expected_tail)

    def test_legacy_and_segmented_overlap_fails_outside_recovery(self) -> None:
        self.append()
        self.migrate()
        self.path.write_bytes(b"")
        with self.assertRaisesRegex(JournalIntegrityError, "overlap"):
            self.journal.tail()

    def test_interrupted_rotation_recovers_without_event_loss(self) -> None:
        for crash_after in ("after_seal", "after_active"):
            with self.subTest(crash_after=crash_after):
                with TemporaryDirectory() as temporary:
                    path = Path(temporary) / "records" / "journal.jsonl"
                    journal = DurableJournal(path)
                    self.append(journal)
                    self.migrate(journal)
                    self.append(journal)
                    before = journal.read_all()
                    with self.assertRaises(JournalError):
                        journal._rotate(crash_after=crash_after)
                    recovered = DurableJournal(path)
                    self.assertTrue(recovered.recover_storage())
                    self.assertEqual(recovered.read_all(), before)
                    appended = self.append(recovered)
                    self.assertEqual(recovered.read_all()[-1], appended)

    def test_interrupted_migration_recovers_at_every_materialization_stage(self) -> None:
        stages = (
            "after_segment",
            "after_seal",
            "after_active",
            "after_manifest",
            "after_legacy_removal",
        )
        for crash_after in stages:
            with self.subTest(crash_after=crash_after):
                with TemporaryDirectory() as temporary:
                    path = Path(temporary) / "records" / "journal.jsonl"
                    journal = DurableJournal(path)
                    self.append(journal)
                    migration = self.migration_event(journal)

                    def interrupt(label: str) -> None:
                        if label == crash_after:
                            raise RuntimeError(label)

                    with self.assertRaisesRegex(RuntimeError, crash_after):
                        journal.materialize_legacy_migration(
                            migration, after_stage=interrupt
                        )
                    recovered = DurableJournal(path)
                    recovered.recover_storage()
                    self.assertEqual(
                        recovered.tail()[0],
                        JournalHead(migration["sequence"], migration["event_id"]),
                    )
                    self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
