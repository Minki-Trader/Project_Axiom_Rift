from __future__ import annotations

from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from axiom_rift.storage.index import (
    IndexRecord,
    LocalIndex,
    LocalIndexError,
)


def _trial(token: int, axis_token: int) -> IndexRecord:
    executable_id = f"executable:{token:064x}"
    return IndexRecord(
        kind="trial",
        record_id=executable_id,
        subject=f"Batch:BAT-{token:04d}",
        status="evaluated",
        fingerprint=executable_id.removeprefix("executable:"),
        payload={
            "executable": {"source_contracts": []},
            "portfolio_axis_identity": f"axis:{axis_token:064x}",
        },
    )


class EffectiveAxisLookupIndexTests(unittest.TestCase):
    def test_allowlisted_single_and_union_lookup_use_expression_index(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "index.sqlite"
            with LocalIndex(path) as index:
                index.put_many((_trial(1, 11), _trial(2, 22), _trial(3, 33)))
                axis_11 = f"axis:{11:064x}"
                axis_33 = f"axis:{33:064x}"
                self.assertEqual(
                    tuple(
                        record.record_id
                        for record in index.records_by_payload_text(
                            "trial",
                            "portfolio_axis_identity",
                            axis_11,
                        )
                    ),
                    (f"executable:{1:064x}",),
                )
                self.assertTrue(
                    all(
                        not detail.startswith("SCAN records")
                        for detail in index.records_by_payload_text_access_shape(
                            "trial",
                            "portfolio_axis_identity",
                            axis_11,
                        )
                    )
                )
                union = index.records_by_payload_text_values(
                    "trial",
                    "portfolio_axis_identity",
                    (axis_33, axis_11, axis_11),
                )
                self.assertEqual(
                    tuple(record.record_id for record in union),
                    (f"executable:{1:064x}", f"executable:{3:064x}"),
                )
                self.assertTrue(
                    all(
                        not detail.startswith("SCAN records")
                        for detail in (
                            index.records_by_payload_text_values_access_shape(
                                "trial",
                                "portfolio_axis_identity",
                                (axis_11, axis_33),
                            )
                        )
                    )
                )
                with self.assertRaisesRegex(ValueError, "not allowlisted"):
                    index.records_by_payload_text(
                        "trial",
                        "$.caller_controlled_path",
                        axis_11,
                    )

    def test_schema_v1_materialization_changes_no_projection_authority(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "index.sqlite"
            with LocalIndex(path) as index:
                index.put_many((_trial(1, 11), _trial(2, 22)))
                before_count = index.record_count()
                before_guard = index.projection_guard()
                before_records = tuple(
                    index.records_by_kind("trial")
                )
            connection = sqlite3.connect(path)
            expression_indexes = tuple(
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'index' AND name LIKE "
                    "'ix_records_kind_payload_%' ORDER BY name"
                ).fetchall()
            )
            for index_name in expression_indexes:
                connection.execute(f'DROP INDEX "{index_name}"')
            connection.execute("PRAGMA user_version = 1")
            connection.commit()
            connection.close()

            with self.assertRaisesRegex(
                LocalIndexError,
                "explicit local-index materialization",
            ):
                LocalIndex.open_read_only(path)
            result = LocalIndex.materialize_payload_lookup_indexes(path)
            self.assertEqual(result["from_schema_version"], 1)
            self.assertEqual(result["to_schema_version"], 3)
            self.assertEqual(result["record_count"], before_count)
            self.assertEqual(result["projection_digest"], before_guard[0])
            with LocalIndex.open_read_only(path) as index:
                self.assertEqual(index.record_count(), before_count)
                self.assertEqual(index.projection_guard(), before_guard)
                self.assertEqual(index.records_by_kind("trial"), before_records)

    def test_unrelated_history_is_not_decoded_by_current_axis_lookup(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "index.sqlite"
            target_axis = f"axis:{9999:064x}"
            with LocalIndex(path) as index:
                index.put_many(
                    tuple(_trial(token, token) for token in range(1, 401))
                    + (_trial(9999, 9999),)
                )
            decoded: list[str] = []
            with LocalIndex.open_read_only(
                path,
                authority_validator=lambda record: decoded.append(record.record_id),
            ) as index:
                records = index.records_by_payload_text(
                    "trial",
                    "portfolio_axis_identity",
                    target_axis,
                )
                self.assertEqual(
                    tuple(record.record_id for record in records),
                    (f"executable:{9999:064x}",),
                )
                self.assertEqual(decoded, [f"executable:{9999:064x}"])
                self.assertTrue(
                    all(
                        not detail.startswith("SCAN records")
                        for detail in index.records_by_payload_text_access_shape(
                            "trial",
                            "portfolio_axis_identity",
                            target_axis,
                        )
                    )
                )


if __name__ == "__main__":
    unittest.main()
