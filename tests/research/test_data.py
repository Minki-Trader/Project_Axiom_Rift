from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import subprocess
import sys
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
MATERIALIZER = Path(__file__).resolve().parents[2] / "scripts" / "materialize_observed_development.py"
OBSERVED_RELATIVE = "data/processed/datasets/observed_fixture.csv"


def _load_materializer_module() -> object:
    spec = importlib.util.spec_from_file_location(
        "observed_development_materializer_subject", MATERIALIZER
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load observed-development materializer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    observed_development: bool = True,
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
    prefix_bytes = HEADER + b"".join(development_rows)
    source_relative = "data/us100_fixture.csv"
    source_path = root / source_relative
    source_path.write_bytes(source_bytes)
    dataset_hash = _sha256(source_bytes)
    prefix_path = root / OBSERVED_RELATIVE
    prefix_path.parent.mkdir(parents=True)
    prefix_path.write_bytes(prefix_bytes)

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
    if observed_development:
        data_manifest["observed_development"] = {
            "path": OBSERVED_RELATIVE,
            "sha256": _sha256(prefix_bytes),
            "byte_count": len(prefix_bytes),
            "row_count": len(development_rows),
            "first_time": _time_text(development_times[0]),
            "last_time": _time_text(development_times[-1]),
            "parent_dataset_sha256": dataset_hash,
            "split_artifact_sha256": split_hash,
            "derivation": "exact_prefix_before_quarantined_tail",
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
    if "observed_development" in data_manifest:
        data_manifest["observed_development"]["split_artifact_sha256"] = split_hash
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

    def test_registered_prefix_loads_without_opening_full_source(self) -> None:
        _write_fixture(self.root)
        expected = ObservedDevelopmentLoader(self.root).load()
        source = (self.root / "data" / "us100_fixture.csv").resolve()
        source.unlink()
        original_open = Path.open

        def guarded_open(path: Path, *args: object, **kwargs: object) -> object:
            if path.resolve() == source:
                raise AssertionError("V2 loader opened the full processed source")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", new=guarded_open):
            actual = ObservedDevelopmentLoader(self.root).load()

        assert_frame_equal(expected.frame, actual.frame)
        self.assertEqual(expected.metadata, actual.metadata)

    def test_split_hash_and_parse_share_one_filesystem_snapshot(self) -> None:
        _write_fixture(self.root)
        split_path = (self.root / "data" / "audits" / "rolling.json").resolve()
        original_bytes = split_path.read_bytes()
        changed = json.loads(original_bytes.decode("ascii"))
        changed["folds"][0]["train_is"]["start"] = "2026-01-05 01:05:00"
        changed["folds"][0]["train_is"]["row_count"] = 7
        changed_text = json.dumps(changed, sort_keys=True, indent=2)
        original_open = Path.open
        split_open_count = 0

        def racing_open(path: Path, *args: object, **kwargs: object) -> object:
            nonlocal split_open_count
            if path.resolve() != split_path:
                return original_open(path, *args, **kwargs)
            split_open_count += 1
            if split_open_count == 1:
                return io.BytesIO(original_bytes)
            return io.StringIO(changed_text)

        with patch.object(Path, "open", new=racing_open):
            loaded = ObservedDevelopmentLoader(self.root).load()

        self.assertEqual(split_open_count, 1)
        self.assertEqual(
            loaded.fold("rw_001").train_is.start,
            pd.Timestamp("2026-01-05 01:00:00"),
        )

    def test_missing_observed_development_fails_before_opening_full_source(self) -> None:
        _write_fixture(self.root)
        data_path = self.root / "foundation" / "data.yaml"
        manifest = yaml.safe_load(data_path.read_text(encoding="ascii"))
        del manifest["observed_development"]
        data_path.write_text(
            yaml.safe_dump(manifest, sort_keys=False), encoding="ascii"
        )
        source = (self.root / "data" / "us100_fixture.csv").resolve()
        original_open = Path.open
        opened_source = False

        def guarded_open(path: Path, *args: object, **kwargs: object) -> object:
            nonlocal opened_source
            if path.resolve() == source:
                opened_source = True
                raise AssertionError("routine loader opened the full processed source")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", new=guarded_open):
            with self.assertRaisesRegex(
                DevelopmentDataError,
                "observed_development is required",
            ):
                ObservedDevelopmentLoader(self.root).load()

        self.assertFalse(opened_source)

    def test_v2_observed_development_binding_mismatches_fail_before_parser(self) -> None:
        cases: dict[str, tuple[str, object]] = {
            "path": ("path", "data/processed/datasets/../escape.csv"),
            "sha256": ("sha256", "0" * 64),
            "byte_count": ("byte_count", 1),
            "row_count": ("row_count", 35),
            "first_time": ("first_time", "2020-01-01 00:00:00"),
            "last_time": ("last_time", "2020-01-01 00:00:00"),
            "parent": ("parent_dataset_sha256", "1" * 64),
            "split": ("split_artifact_sha256", "2" * 64),
            "derivation": ("derivation", "unsafe_copy"),
        }
        for name, (field, value) in cases.items():
            with self.subTest(name=name):
                case_root = self.root / name
                _write_fixture(case_root, observed_development=True)
                data_path = case_root / "foundation" / "data.yaml"
                manifest = yaml.safe_load(data_path.read_text(encoding="ascii"))
                manifest["observed_development"][field] = value
                data_path.write_text(
                    yaml.safe_dump(manifest, sort_keys=False), encoding="ascii"
                )
                with patch.object(data_module.pd, "read_csv") as parser:
                    with self.assertRaises(DevelopmentDataError):
                        ObservedDevelopmentLoader(case_root).load()
                    parser.assert_not_called()

    def test_materializer_publishes_only_exact_prefix_and_is_idempotent(self) -> None:
        _write_fixture(self.root, observed_development=False)
        command = (
            sys.executable,
            str(MATERIALIZER),
            "--repository-root",
            str(self.root),
        )

        first = subprocess.run(command, check=False, capture_output=True, text=True)

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertNotIn(SENTINEL.decode("ascii"), first.stdout)
        report = json.loads(first.stdout)
        self.assertFalse(report["tail_values_exposed"])
        self.assertEqual(report["status"], "materialized")
        observed = report["observed_development"]
        destination = self.root / observed["path"]
        content = destination.read_bytes()
        self.assertNotIn(SENTINEL, content)
        self.assertNotIn(b"SEALED_SECOND_ROW", content)
        self.assertEqual(content, (self.root / OBSERVED_RELATIVE).read_bytes())
        first_mtime = destination.stat().st_mtime_ns

        second = subprocess.run(command, check=False, capture_output=True, text=True)

        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(second.stdout)["status"], "existing_exact")
        self.assertEqual(destination.stat().st_mtime_ns, first_mtime)
        data_path = self.root / "foundation" / "data.yaml"
        manifest = yaml.safe_load(data_path.read_text(encoding="ascii"))
        self.assertNotIn("observed_development", manifest)
        manifest["observed_development"] = observed
        data_path.write_text(
            yaml.safe_dump(manifest, sort_keys=False), encoding="ascii"
        )
        loaded = ObservedDevelopmentLoader(self.root).load()
        self.assertEqual(len(loaded.frame), 36)
        self.assertEqual(loaded.metadata.development_prefix_sha256, observed["sha256"])
        self.assertEqual(loaded.metadata.prefix_byte_count, observed["byte_count"])

    def test_materializer_refuses_to_replace_mismatched_existing_output(self) -> None:
        _write_fixture(self.root, observed_development=False)
        destination = (
            self.root
            / "data"
            / "processed"
            / "datasets"
            / "us100_m5_observed_development.csv"
        )
        destination.write_bytes(b"preexisting-mismatch\n")

        result = subprocess.run(
            (
                sys.executable,
                str(MATERIALIZER),
                "--repository-root",
                str(self.root),
            ),
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("identity differs", result.stderr)
        self.assertEqual(destination.read_bytes(), b"preexisting-mismatch\n")

    def test_materializer_rejects_concurrent_symlink_publication(self) -> None:
        subject = _load_materializer_module()
        lane = self.root / "data" / "processed" / "datasets"
        lane.mkdir(parents=True)
        destination = lane / "race.csv"
        target = self.root / "outside.csv"
        payload = b"approved-prefix\n"
        target.write_bytes(payload)
        probe = lane / "probe-link.csv"
        try:
            probe.symlink_to(target)
            probe.unlink()
        except OSError as exc:
            self.skipTest(f"file symlinks unavailable: {exc}")
        temporary = lane / ".race.tmp"
        temporary.write_bytes(payload)

        def race_link(source: object, published: object) -> None:
            self.assertEqual(Path(source), temporary)
            Path(published).symlink_to(target)
            raise FileExistsError("simulated publication race")

        observed = {
            "path": "data/processed/datasets/race.csv",
            "sha256": _sha256(payload),
            "byte_count": len(payload),
        }
        with patch.object(subject.os, "link", side_effect=race_link):
            with self.assertRaisesRegex(subject.MaterializationError, "link-like"):
                subject._publish_exact(
                    self.root.resolve(), temporary, destination, observed
                )

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

    def test_parent_manifest_binding_is_checked_before_parser(self) -> None:
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
            "nonpositive": (
                5,
                ",105.0,107.0,103.0,106.0",
                ",-105.0,-103.0,-107.0,-106.0",
            ),
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
        prefix = self.root / OBSERVED_RELATIVE
        lines = prefix.read_bytes().splitlines(keepends=True)
        lines[2] = lines[1].split(b",", 1)[0] + b"," + lines[2].split(b",", 1)[1]
        prefix_bytes = b"".join(lines)
        prefix.write_bytes(prefix_bytes)

        data_path = self.root / "foundation" / "data.yaml"
        data_manifest = yaml.safe_load(data_path.read_text(encoding="ascii"))
        data_manifest["observed_development"]["sha256"] = _sha256(prefix_bytes)
        data_manifest["observed_development"]["byte_count"] = len(prefix_bytes)
        data_path.write_text(
            yaml.safe_dump(data_manifest, sort_keys=False), encoding="ascii"
        )

        with self.assertRaisesRegex(DevelopmentDataError, "strictly increasing"):
            ObservedDevelopmentLoader(self.root).load()


if __name__ == "__main__":
    unittest.main()
