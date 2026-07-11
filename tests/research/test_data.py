from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import yaml
from pandas.testing import assert_frame_equal

from axiom_rift.core.identity import canonical_digest
from axiom_rift.research import data as data_module
from axiom_rift.research.data import (
    DevelopmentDataError,
    ObservedDevelopmentLoader,
    load_observed_development,
)


HEADER = b"time,open,high,low,close,tick_volume,spread,real_volume\n"
SENTINEL = b"FORBIDDEN_TAIL_SENTINEL"


def _time_text(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _development_row(value: datetime, index: int) -> bytes:
    open_value = 100.0 + index
    return (
        f"{_time_text(value)},{open_value},{open_value + 2.0},"
        f"{open_value - 2.0},{open_value + 1.0},{10 + index},2,0\n"
    ).encode("ascii")


def _tail_row(value: datetime, marker: bytes) -> bytes:
    return (
        _time_text(value).encode("ascii")
        + b","
        + marker
        + b",TAIL_HIGH,TAIL_LOW,TAIL_CLOSE,TAIL_TICKS,TAIL_SPREAD,TAIL_REAL\n"
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _window(times: list[datetime], start: int, end: int) -> dict[str, object]:
    return {
        "start": _time_text(times[start]),
        "end": _time_text(times[end]),
        "row_count": end - start + 1,
    }


def _write_fixture(
    root: Path,
    *,
    tail_markers: tuple[bytes, ...] = (SENTINEL, b"SEALED_SECOND_ROW"),
    development_mutation: tuple[int, str, str] | None = None,
) -> None:
    foundation = root / "foundation"
    data_directory = root / "data"
    audit_directory = data_directory / "audits"
    foundation.mkdir(parents=True)
    audit_directory.mkdir(parents=True)

    start = datetime(2026, 1, 5, 1, 0)
    development_times = [start + timedelta(minutes=5 * index) for index in range(36)]
    development_rows = [
        _development_row(value, index)
        for index, value in enumerate(development_times)
    ]
    if development_mutation is not None:
        row_index, original, replacement = development_mutation
        development_rows[row_index] = development_rows[row_index].replace(
            original.encode("ascii"), replacement.encode("ascii"), 1
        )
    tail_times = [
        development_times[-1] + timedelta(minutes=5 * (index + 1))
        for index in range(len(tail_markers))
    ]
    tail_rows = [
        _tail_row(value, marker)
        for value, marker in zip(tail_times, tail_markers, strict=True)
    ]
    source_bytes = HEADER + b"".join(development_rows) + b"".join(tail_rows)
    source_relative = "data/us100_fixture.csv"
    source_path = root / source_relative
    source_path.write_bytes(source_bytes)
    dataset_hash = _sha256(source_bytes)

    folds: list[dict[str, object]] = []
    for index in range(9):
        test_end = 11 + (3 * index)
        folds.append(
            {
                "fold_id": f"rw_{index + 1:03d}",
                "train_is": _window(development_times, 0, test_end - 4),
                "validation_oos": _window(
                    development_times, test_end - 3, test_end - 2
                ),
                "test_oos": _window(
                    development_times, test_end - 1, test_end
                ),
            }
        )
    split = {
        "schema": "axiom_rift_rolling_windows_v1",
        "source_base_frame": source_relative,
        "fold_count": 9,
        "folds": folds,
        "tail_holdout_partial": {
            "start": _time_text(tail_times[0]),
            "end": _time_text(tail_times[-1]),
            "row_count": len(tail_rows),
        },
    }
    split_bytes = json.dumps(split, sort_keys=True, indent=2).encode("ascii")
    split_relative = "data/audits/rolling.json"
    (root / split_relative).write_bytes(split_bytes)
    split_hash = _sha256(split_bytes)

    data_manifest = {
        "schema": "data_foundation",
        "processed": {
            "path": source_relative,
            "sha256": dataset_hash,
            "row_count": len(development_rows) + len(tail_rows),
            "first_time": _time_text(development_times[0]),
            "last_time": _time_text(tail_times[-1]),
            "fields": [
                "time",
                "open",
                "high",
                "low",
                "close",
                "tick_volume",
                "spread",
                "real_volume",
            ],
        },
        "split_artifact": {"path": split_relative, "sha256": split_hash},
        "volume_semantics": {
            "tick_volume": "broker_tick_count_not_traded_volume",
            "real_volume": {"eligible": False, "nonzero_rows": 0},
        },
    }
    (foundation / "data.yaml").write_text(
        yaml.safe_dump(data_manifest, sort_keys=False), encoding="ascii"
    )

    identity_inputs = {
        "dataset_sha256": dataset_hash,
        "split_artifact_sha256": split_hash,
        "observed_window_count": 9,
        "last_observed_development_time": _time_text(development_times[-1]),
    }
    exposure = {
        "schema": "data_exposure_foundation",
        "observed_development_material": {
            "identity": canonical_digest(
                domain="development-material", payload=identity_inputs
            ),
            "identity_domain": "development-material",
            "identity_inputs": identity_inputs,
            "may_be_relabelled_fresh": False,
        },
        "quarantined_tail": {
            "start": _time_text(tail_times[0]),
            "end": _time_text(tail_times[-1]),
            "status": "quarantine_pending_access_audit",
            "scientific_raw_access_allowed": False,
            "claim_use_allowed": False,
        },
    }
    (foundation / "data_exposure.yaml").write_text(
        yaml.safe_dump(exposure, sort_keys=False), encoding="ascii"
    )


def _rewrite_split(
    root: Path,
    mutation: Callable[[dict[str, object]], None],
) -> None:
    split_path = root / "data" / "audits" / "rolling.json"
    split = json.loads(split_path.read_text(encoding="ascii"))
    mutation(split)
    split_bytes = json.dumps(split, sort_keys=True, indent=2).encode("ascii")
    split_path.write_bytes(split_bytes)
    split_hash = _sha256(split_bytes)

    data_path = root / "foundation" / "data.yaml"
    data_manifest = yaml.safe_load(data_path.read_text(encoding="ascii"))
    data_manifest["split_artifact"]["sha256"] = split_hash
    data_path.write_text(
        yaml.safe_dump(data_manifest, sort_keys=False), encoding="ascii"
    )

    exposure_path = root / "foundation" / "data_exposure.yaml"
    exposure = yaml.safe_load(exposure_path.read_text(encoding="ascii"))
    material = exposure["observed_development_material"]
    material["identity_inputs"]["split_artifact_sha256"] = split_hash
    material["identity"] = canonical_digest(
        domain=material["identity_domain"], payload=material["identity_inputs"]
    )
    exposure_path.write_text(
        yaml.safe_dump(exposure, sort_keys=False), encoding="ascii"
    )


class ObservedDevelopmentLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_forbidden_tail_never_reaches_parser_or_output(self) -> None:
        _write_fixture(self.root)
        actual_read_csv = pd.read_csv
        parser_payloads: list[bytes] = []
        parser_kwargs: list[dict[str, object]] = []

        def guarded_parser(
            parser_input: io.BytesIO, *args: object, **kwargs: object
        ) -> pd.DataFrame:
            self.assertIsInstance(parser_input, io.BytesIO)
            payload = parser_input.getvalue()
            parser_payloads.append(payload)
            parser_kwargs.append(dict(kwargs))
            self.assertNotIn(SENTINEL, payload)
            self.assertNotIn(b"SEALED_SECOND_ROW", payload)
            return actual_read_csv(io.BytesIO(payload), *args, **kwargs)

        with patch.object(data_module.pd, "read_csv", side_effect=guarded_parser):
            result = load_observed_development(self.root)

        self.assertEqual(len(parser_payloads), 1)
        self.assertEqual(len(result.frame), 36)
        self.assertEqual(result.metadata.development_row_count, 36)
        self.assertEqual(result.metadata.quarantined_row_count, 2)
        self.assertEqual(len(result.metadata.folds), 9)
        self.assertEqual(result.fold("rw_009").test_oos.end, result.frame.time.iloc[-1])
        self.assertNotIn("real_volume", result.frame.columns)
        self.assertNotIn("real_volume", parser_kwargs[0]["usecols"])
        self.assertNotIn("FORBIDDEN", result.frame.to_string())

    def test_quarantine_append_preserves_prefix_and_frame(self) -> None:
        first = self.root / "first"
        second = self.root / "second"
        _write_fixture(first, tail_markers=(SENTINEL,))
        _write_fixture(
            second,
            tail_markers=(SENTINEL, b"SEALED_APPEND_ONE", b"SEALED_APPEND_TWO"),
        )

        before = ObservedDevelopmentLoader(first).load()
        after = ObservedDevelopmentLoader(second).load()

        assert_frame_equal(before.frame, after.frame)
        self.assertEqual(
            before.metadata.development_prefix_sha256,
            after.metadata.development_prefix_sha256,
        )
        self.assertEqual(before.metadata.prefix_byte_count, after.metadata.prefix_byte_count)
        self.assertEqual(
            before.metadata.last_development_time,
            after.metadata.last_development_time,
        )
        self.assertNotEqual(before.metadata.dataset_sha256, after.metadata.dataset_sha256)
        self.assertEqual(before.metadata.quarantined_row_count, 1)
        self.assertEqual(after.metadata.quarantined_row_count, 3)

    def test_real_volume_request_is_rejected(self) -> None:
        _write_fixture(self.root)
        with self.assertRaisesRegex(DevelopmentDataError, "real_volume"):
            ObservedDevelopmentLoader(self.root).load(
                columns=("time", "close", "real_volume")
            )

    def test_reordered_inter_fold_test_windows_are_rejected(self) -> None:
        _write_fixture(self.root)

        def reorder(split: dict[str, object]) -> None:
            folds = split["folds"]
            folds[0], folds[1] = folds[1], folds[0]

        _rewrite_split(self.root, reorder)
        with self.assertRaisesRegex(DevelopmentDataError, "strictly non-overlapping"):
            ObservedDevelopmentLoader(self.root).load()

    def test_overlapping_inter_fold_test_windows_are_rejected(self) -> None:
        _write_fixture(self.root)

        def overlap(split: dict[str, object]) -> None:
            folds = split["folds"]
            first_test = folds[0]["test_oos"]
            second_test = folds[1]["test_oos"]
            first_test["end"] = second_test["start"]
            first_test["row_count"] = 4

        _rewrite_split(self.root, overlap)
        with self.assertRaisesRegex(DevelopmentDataError, "strictly non-overlapping"):
            ObservedDevelopmentLoader(self.root).load()

    def test_fold_window_row_count_mismatch_is_rejected(self) -> None:
        _write_fixture(self.root)

        def alter_row_count(split: dict[str, object]) -> None:
            window = split["folds"][4]["validation_oos"]
            window["row_count"] += 1

        _rewrite_split(self.root, alter_row_count)
        with self.assertRaisesRegex(
            DevelopmentDataError,
            "rw_005.validation_oos row count does not match development frame",
        ):
            ObservedDevelopmentLoader(self.root).load()

    def test_full_source_identity_is_checked_before_parser(self) -> None:
        cases = {
            "hash": ("sha256", "0" * 64),
            "row_count": ("row_count", 999),
            "last_time": ("last_time", "2099-01-01 00:00:00"),
        }
        for name, (key, value) in cases.items():
            with self.subTest(name=name):
                case_root = self.root / name
                _write_fixture(case_root)
                manifest_path = case_root / "foundation" / "data.yaml"
                manifest = yaml.safe_load(manifest_path.read_text(encoding="ascii"))
                manifest["processed"][key] = value
                manifest_path.write_text(
                    yaml.safe_dump(manifest, sort_keys=False), encoding="ascii"
                )
                with patch.object(data_module.pd, "read_csv") as parser:
                    with self.assertRaises(DevelopmentDataError):
                        ObservedDevelopmentLoader(case_root).load()
                    parser.assert_not_called()

    def test_development_guards_reject_invalid_values(self) -> None:
        cases = {
            "nonfinite": (4, ",104.0,106.0", ",nan,106.0"),
            "ohlc": (5, ",105.0,107.0,103.0,106.0", ",105.0,104.0,103.0,106.0"),
            "spread": (6, ",16,2,0", ",16,-1,0"),
        }
        for name, mutation in cases.items():
            with self.subTest(name=name):
                case_root = self.root / name
                _write_fixture(case_root, development_mutation=mutation)
                with self.assertRaises(DevelopmentDataError):
                    ObservedDevelopmentLoader(case_root).load()

    def test_timestamp_guard_rejects_duplicate_development_row(self) -> None:
        _write_fixture(self.root)
        source = self.root / "data" / "us100_fixture.csv"
        lines = source.read_bytes().splitlines(keepends=True)
        lines[2] = lines[1].split(b",", 1)[0] + b"," + lines[2].split(b",", 1)[1]
        source_bytes = b"".join(lines)
        source.write_bytes(source_bytes)

        data_path = self.root / "foundation" / "data.yaml"
        data_manifest = yaml.safe_load(data_path.read_text(encoding="ascii"))
        data_manifest["processed"]["sha256"] = _sha256(source_bytes)
        data_path.write_text(
            yaml.safe_dump(data_manifest, sort_keys=False), encoding="ascii"
        )

        exposure_path = self.root / "foundation" / "data_exposure.yaml"
        exposure = yaml.safe_load(exposure_path.read_text(encoding="ascii"))
        identity_inputs = exposure["observed_development_material"]["identity_inputs"]
        identity_inputs["dataset_sha256"] = _sha256(source_bytes)
        exposure["observed_development_material"]["identity"] = canonical_digest(
            domain="development-material", payload=identity_inputs
        )
        exposure_path.write_text(
            yaml.safe_dump(exposure, sort_keys=False), encoding="ascii"
        )

        with self.assertRaisesRegex(DevelopmentDataError, "strictly increasing"):
            ObservedDevelopmentLoader(self.root).load()


if __name__ == "__main__":
    unittest.main()
