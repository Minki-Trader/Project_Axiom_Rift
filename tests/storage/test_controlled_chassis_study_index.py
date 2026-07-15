from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from axiom_rift.core.canonical import canonical_text
from axiom_rift.storage.index import (
    IndexIntegrityError,
    IndexRecord,
    LocalIndex,
    LocalIndexError,
)


def _record(
    token: int,
    *,
    kind: str = "study-open",
    controlled_chassis: object = None,
) -> IndexRecord:
    payload = {"fixture": token}
    if controlled_chassis is not None:
        payload["controlled_chassis"] = controlled_chassis
    return IndexRecord(
        kind=kind,
        record_id=f"record-{token:04d}",
        subject=f"Study:STU-{token:04d}",
        status="open",
        fingerprint=f"{token:064x}",
        payload=payload,
    )


def _drop_presence_projection(path: Path, *, version: int) -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
        triggers = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger' "
            "AND name LIKE '%controlled_chassis_study%'"
        ).fetchall()
        for (name,) in triggers:
            connection.execute(f'DROP TRIGGER "{name}"')
        connection.execute("DROP TABLE controlled_chassis_study_stats")
        connection.execute(f"PRAGMA user_version = {version}")


class ControlledChassisStudyIndexTests(unittest.TestCase):
    def test_presence_is_schema_bound_exact_and_decode_free(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "index.sqlite"
            with LocalIndex(path) as index:
                self.assertFalse(index.has_controlled_chassis_study())
                index.put_many(
                    (
                        _record(1, kind="trial", controlled_chassis={}),
                        _record(2, controlled_chassis=[]),
                        _record(3),
                    )
                )
                self.assertFalse(index.has_controlled_chassis_study())
                index.put(
                    _record(
                        4,
                        controlled_chassis={
                            "unrelated_axis": "axis:any",
                            "unrelated_data_contract": "data:any",
                        },
                    )
                )
                self.assertTrue(index.has_controlled_chassis_study())
                self.assertEqual(
                    index.controlled_chassis_study_guard(),
                    (1, True),
                )

            decoded: list[str] = []
            with LocalIndex.open_read_only(
                path,
                authority_validator=lambda record: decoded.append(
                    record.record_id
                ),
            ) as index:
                self.assertTrue(index.has_controlled_chassis_study())
                self.assertEqual(decoded, [])
                shape = index.has_controlled_chassis_study_access_shape()
                self.assertTrue(
                    any("USING PRIMARY KEY" in detail for detail in shape)
                )
                self.assertFalse(any(detail.startswith("SCAN") for detail in shape))

    def test_record_or_guard_tamper_fails_before_a_false_answer(self) -> None:
        cases = ("record", "guard")
        for case in cases:
            with self.subTest(case=case), TemporaryDirectory() as temporary:
                path = Path(temporary) / "index.sqlite"
                study = _record(1, controlled_chassis={"schema": "any.v1"})
                with LocalIndex(path) as index:
                    index.put(study)
                    if case == "record":
                        index._connection.execute(  # noqa: SLF001
                            "UPDATE records SET payload_json = ? "
                            "WHERE kind = ? AND record_id = ?",
                            (
                                canonical_text(
                                    {"controlled_chassis": [], "fixture": 1}
                                ),
                                study.kind,
                                study.record_id,
                            ),
                        )
                    else:
                        index._connection.execute(  # noqa: SLF001
                            "UPDATE controlled_chassis_study_stats "
                            "SET study_count = 0 WHERE singleton = 1"
                        )
                    with self.assertRaises(IndexIntegrityError):
                        index.has_controlled_chassis_study()
                with self.assertRaises(IndexIntegrityError):
                    LocalIndex.open_read_only(path)

    def test_missing_table_or_trigger_blocks_read_only_open(self) -> None:
        for case in ("table", "trigger"):
            with self.subTest(case=case), TemporaryDirectory() as temporary:
                path = Path(temporary) / "index.sqlite"
                with LocalIndex(path):
                    pass
                with closing(sqlite3.connect(path)) as connection, connection:
                    if case == "table":
                        triggers = connection.execute(
                            "SELECT name FROM sqlite_master WHERE type = 'trigger' "
                            "AND name LIKE '%controlled_chassis_study%'"
                        ).fetchall()
                        for (name,) in triggers:
                            connection.execute(f'DROP TRIGGER "{name}"')
                        connection.execute(
                            "DROP TABLE controlled_chassis_study_stats"
                        )
                    else:
                        connection.execute(
                            "DROP TRIGGER records_controlled_chassis_study_insert"
                        )
                with self.assertRaisesRegex(
                    LocalIndexError,
                    "controlled-chassis Study",
                ):
                    LocalIndex.open_read_only(path)

    def test_writable_recovery_reanchors_a_corrupt_presence_guard(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "index.sqlite"
            study = _record(1, controlled_chassis={"schema": "any.v1"})
            with LocalIndex(path) as index:
                index.put(study)
                index._connection.execute(  # noqa: SLF001 - adversarial fixture
                    "UPDATE controlled_chassis_study_stats "
                    "SET study_count = 0 WHERE singleton = 1"
                )
            with LocalIndex(path) as recovery:
                with self.assertRaises(IndexIntegrityError):
                    recovery.check_integrity()
                recovery.rebuild((study,))
                recovery.check_integrity()
                self.assertTrue(recovery.has_controlled_chassis_study())

    def test_v2_projection_materializes_exact_existing_presence(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "index.sqlite"
            with LocalIndex(path) as index:
                index.put(_record(1, controlled_chassis={"schema": "any.v1"}))
                authority_guard = index.projection_guard()
            _drop_presence_projection(path, version=2)

            result = LocalIndex.materialize_payload_lookup_indexes(path)

            self.assertEqual(result["from_schema_version"], 2)
            self.assertEqual(result["to_schema_version"], 3)
            self.assertEqual(result["controlled_chassis_study_count"], 1)
            with LocalIndex.open_read_only(path) as index:
                self.assertEqual(index.projection_guard(), authority_guard)
                self.assertTrue(index.has_controlled_chassis_study())


if __name__ == "__main__":
    unittest.main()
