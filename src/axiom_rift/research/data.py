"""Quarantine-safe loading of the Foundation development CSV prefix."""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping

import numpy as np
import pandas as pd
import yaml

from axiom_rift.core.identity import canonical_digest


_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
_SOURCE_FIELDS = (
    "time",
    "open",
    "high",
    "low",
    "close",
    "tick_volume",
    "spread",
    "real_volume",
)
_ELIGIBLE_FIELDS = _SOURCE_FIELDS[:-1]
_NUMERIC_FIELDS = _ELIGIBLE_FIELDS[1:]
_OBSERVED_DEVELOPMENT_FIELDS = frozenset(
    {
        "path",
        "sha256",
        "byte_count",
        "row_count",
        "first_time",
        "last_time",
        "parent_dataset_sha256",
        "split_artifact_sha256",
        "derivation",
    }
)
_OBSERVED_DEVELOPMENT_DERIVATION = "exact_prefix_before_quarantined_tail"


class DevelopmentDataError(ValueError):
    """Raised before unsafe or invalid data can enter scientific code."""


@dataclass(frozen=True, slots=True)
class WindowMetadata:
    start: pd.Timestamp
    end: pd.Timestamp
    row_count: int


@dataclass(frozen=True, slots=True)
class RollingFoldMetadata:
    fold_id: str
    train_is: WindowMetadata
    validation_oos: WindowMetadata
    test_oos: WindowMetadata


@dataclass(frozen=True, slots=True)
class DevelopmentMetadata:
    material_identity: str
    dataset_sha256: str
    split_artifact_sha256: str
    development_prefix_sha256: str
    source_path: Path
    source_row_count: int
    development_row_count: int
    quarantined_row_count: int
    prefix_byte_count: int
    first_time: pd.Timestamp
    last_development_time: pd.Timestamp
    quarantined_start: pd.Timestamp
    quarantined_end: pd.Timestamp
    source_last_time: pd.Timestamp
    source_fields: tuple[str, ...]
    fields: tuple[str, ...]
    folds: tuple[RollingFoldMetadata, ...]


@dataclass(frozen=True, slots=True)
class ObservedDevelopmentData:
    frame: pd.DataFrame
    metadata: DevelopmentMetadata

    def fold(self, fold_id: str) -> RollingFoldMetadata:
        """Return one immutable rolling-fold description by id."""

        for fold in self.metadata.folds:
            if fold.fold_id == fold_id:
                return fold
        raise KeyError(f"unknown rolling fold: {fold_id}")


@dataclass(frozen=True, slots=True)
class _ScanResult:
    parser_input: io.BytesIO
    prefix_sha256: str
    prefix_byte_count: int


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if type(value) is not dict:
        raise DevelopmentDataError(f"{name} must be a mapping")
    return value


def _exact_mapping(
    value: object, name: str, *, fields: frozenset[str]
) -> Mapping[str, object]:
    payload = _mapping(value, name)
    if set(payload) != fields:
        raise DevelopmentDataError(f"{name} fields differ from the exact schema")
    return payload


def _list(value: object, name: str) -> list[object]:
    if type(value) is not list:
        raise DevelopmentDataError(f"{name} must be a list")
    return value


def _ascii(value: object, name: str) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise DevelopmentDataError(f"{name} must be a non-empty ASCII string")
    return value


def _integer(value: object, name: str, *, positive: bool = False) -> int:
    if type(value) is not int or value < (1 if positive else 0):
        qualifier = "positive" if positive else "non-negative"
        raise DevelopmentDataError(f"{name} must be a {qualifier} integer")
    return value


def _sha256(value: object, name: str) -> str:
    digest = _ascii(value, name)
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise DevelopmentDataError(f"{name} must be a lowercase SHA256 digest")
    return digest


def _timestamp(value: object, name: str) -> pd.Timestamp:
    text = _ascii(value, name)
    try:
        parsed = pd.to_datetime(text, format=_TIME_FORMAT, errors="raise")
    except (TypeError, ValueError) as exc:
        raise DevelopmentDataError(f"{name} must use {_TIME_FORMAT}") from exc
    timestamp = pd.Timestamp(parsed)
    if timestamp.tzinfo is not None:
        raise DevelopmentDataError(f"{name} must be a naive broker timestamp")
    return timestamp


def _load_yaml(path: Path, name: str) -> Mapping[str, object]:
    if not path.is_file():
        raise DevelopmentDataError(f"{name} not found: {path}")
    try:
        value = yaml.safe_load(path.read_text(encoding="ascii"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise DevelopmentDataError(f"cannot read {name}: {path}") from exc
    return _mapping(value, name)


def _load_json(path: Path, name: str) -> Mapping[str, object]:
    if not path.is_file():
        raise DevelopmentDataError(f"{name} not found: {path}")
    try:
        value = json.loads(path.read_text(encoding="ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DevelopmentDataError(f"cannot read {name}: {path}") from exc
    return _mapping(value, name)


def _resolve_inside(root: Path, value: object, name: str) -> Path:
    relative = Path(_ascii(value, name))
    candidate = relative.resolve() if relative.is_absolute() else (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise DevelopmentDataError(f"{name} must resolve inside the repository") from exc
    return candidate


def _resolve_observed_development_path(root: Path, value: object) -> Path:
    name = "data.observed_development.path"
    text = _ascii(value, name)
    relative = PurePosixPath(text)
    lane = PurePosixPath("data/processed/datasets")
    if (
        any(
            character
            not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_./-"
            for character in text
        )
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.as_posix() != text
        or relative.parts[: len(lane.parts)] != lane.parts
        or len(relative.parts) <= len(lane.parts)
    ):
        raise DevelopmentDataError(
            "data.observed_development.path must remain in its canonical data lane"
        )
    candidate = root.joinpath(*relative.parts)
    cursor = candidate
    while cursor != root:
        is_junction = getattr(cursor, "is_junction", None)
        if cursor.is_symlink() or bool(
            is_junction is not None and is_junction()
        ):
            raise DevelopmentDataError(
                "data.observed_development.path traverses a link-like path"
            )
        cursor = cursor.parent
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise DevelopmentDataError(
            "data.observed_development.path is unavailable"
        ) from exc
    if resolved != candidate or not candidate.is_file():
        raise DevelopmentDataError(
            "data.observed_development.path is not a confined regular file"
        )
    return candidate


def _hash_file(path: Path, name: str) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise DevelopmentDataError(f"cannot hash {name}: {path}") from exc
    return digest.hexdigest()


def _window(value: object, name: str) -> WindowMetadata:
    payload = _mapping(value, name)
    start = _timestamp(payload.get("start"), f"{name}.start")
    end = _timestamp(payload.get("end"), f"{name}.end")
    row_count = _integer(payload.get("row_count"), f"{name}.row_count", positive=True)
    if start > end:
        raise DevelopmentDataError(f"{name} start must not follow end")
    return WindowMetadata(start=start, end=end, row_count=row_count)


def _folds(
    split: Mapping[str, object],
    *,
    expected_count: int,
    source_first_time: pd.Timestamp,
    development_last_time: pd.Timestamp,
) -> tuple[RollingFoldMetadata, ...]:
    declared_count = _integer(split.get("fold_count"), "split.fold_count", positive=True)
    values = _list(split.get("folds"), "split.folds")
    if declared_count != expected_count or len(values) != expected_count:
        raise DevelopmentDataError("rolling fold count does not match development exposure")

    result: list[RollingFoldMetadata] = []
    seen_ids: set[str] = set()
    previous_test_end: pd.Timestamp | None = None
    for index, value in enumerate(values):
        payload = _mapping(value, f"split.folds[{index}]")
        fold_id = _ascii(payload.get("fold_id"), f"split.folds[{index}].fold_id")
        if fold_id in seen_ids:
            raise DevelopmentDataError("rolling fold ids must be unique")
        seen_ids.add(fold_id)
        train = _window(payload.get("train_is"), f"{fold_id}.train_is")
        validation = _window(
            payload.get("validation_oos"), f"{fold_id}.validation_oos"
        )
        test = _window(payload.get("test_oos"), f"{fold_id}.test_oos")
        if not (train.end < validation.start and validation.end < test.start):
            raise DevelopmentDataError(f"{fold_id} windows must be ordered and disjoint")
        if train.start < source_first_time or test.end > development_last_time:
            raise DevelopmentDataError(f"{fold_id} lies outside observed development")
        if previous_test_end is not None and test.start <= previous_test_end:
            raise DevelopmentDataError(
                "rolling test windows must be strictly non-overlapping"
            )
        previous_test_end = test.end
        result.append(
            RollingFoldMetadata(
                fold_id=fold_id,
                train_is=train,
                validation_oos=validation,
                test_oos=test,
            )
        )
    if result[-1].test_oos.end != development_last_time:
        raise DevelopmentDataError(
            "last rolling test window must end at the development boundary"
        )
    return tuple(result)


def _record_body(raw_line: bytes, name: str) -> bytes:
    body = raw_line
    if body.endswith(b"\n"):
        body = body[:-1]
        if body.endswith(b"\r"):
            body = body[:-1]
    if not body:
        raise DevelopmentDataError(f"{name} contains an empty CSV record")
    return body


def _raw_timestamp(record: bytes, name: str) -> bytes:
    timestamp, separator, _ = record.partition(b",")
    if not separator or len(timestamp) != 19:
        raise DevelopmentDataError(f"{name} has an invalid timestamp field boundary")
    return timestamp


def _scan_source(
    path: Path,
    *,
    expected_sha256: str,
    expected_fields: tuple[str, ...],
    expected_row_count: int,
    development_row_count: int,
    expected_first_time: str,
    expected_development_last_time: str,
    expected_quarantine_start: str,
    expected_source_last_time: str,
) -> _ScanResult:
    """Hash all bytes but copy only the allowed prefix into parser memory."""

    expected_header = b",".join(field.encode("ascii") for field in expected_fields)
    expected_times = {
        "first": expected_first_time.encode("ascii"),
        "development_last": expected_development_last_time.encode("ascii"),
        "quarantine_start": expected_quarantine_start.encode("ascii"),
        "source_last": expected_source_last_time.encode("ascii"),
    }
    full_hash = hashlib.sha256()
    prefix_hash = hashlib.sha256()
    prefix = io.BytesIO()
    row_count = 0
    first_time: bytes | None = None
    development_last_time: bytes | None = None
    quarantine_start: bytes | None = None
    source_last_time: bytes | None = None

    try:
        with path.open("rb") as handle:
            header = handle.readline()
            if not header:
                raise DevelopmentDataError("processed CSV is empty")
            full_hash.update(header)
            prefix_hash.update(header)
            prefix.write(header)
            if _record_body(header, "processed CSV header") != expected_header:
                raise DevelopmentDataError("processed CSV schema or field order changed")

            for raw_line in handle:
                full_hash.update(raw_line)
                row_count += 1
                record = _record_body(raw_line, "processed CSV")
                timestamp = _raw_timestamp(record, "processed CSV")
                if row_count == 1:
                    first_time = timestamp
                if row_count <= development_row_count:
                    prefix_hash.update(raw_line)
                    prefix.write(raw_line)
                if row_count == development_row_count:
                    development_last_time = timestamp
                elif row_count == development_row_count + 1:
                    quarantine_start = timestamp
                source_last_time = timestamp
    except OSError as exc:
        prefix.close()
        raise DevelopmentDataError(f"cannot scan processed CSV: {path}") from exc
    except Exception:
        prefix.close()
        raise

    checks = (
        (row_count == expected_row_count, "processed CSV row count changed"),
        (full_hash.hexdigest() == expected_sha256, "processed CSV SHA256 changed"),
        (first_time == expected_times["first"], "processed CSV first time changed"),
        (
            development_last_time == expected_times["development_last"],
            "development prefix boundary changed",
        ),
        (
            quarantine_start == expected_times["quarantine_start"],
            "quarantine start boundary changed",
        ),
        (
            source_last_time == expected_times["source_last"],
            "processed CSV last time changed",
        ),
    )
    for valid, message in checks:
        if not valid:
            prefix.close()
            raise DevelopmentDataError(message)
    prefix.seek(0)
    return _ScanResult(
        parser_input=prefix,
        prefix_sha256=prefix_hash.hexdigest(),
        prefix_byte_count=prefix.getbuffer().nbytes,
    )


def _scan_observed_development(
    path: Path,
    *,
    expected_sha256: str,
    expected_byte_count: int,
    expected_fields: tuple[str, ...],
    expected_row_count: int,
    expected_first_time: str,
    expected_last_time: str,
) -> _ScanResult:
    """Verify and buffer an already materialized development-only CSV."""

    expected_header = b",".join(field.encode("ascii") for field in expected_fields)
    expected_first = expected_first_time.encode("ascii")
    expected_last = expected_last_time.encode("ascii")
    digest = hashlib.sha256()
    parser_input = io.BytesIO()
    byte_count = 0
    row_count = 0
    first_time: bytes | None = None
    last_time: bytes | None = None

    try:
        with path.open("rb") as handle:
            header = handle.readline()
            if not header:
                raise DevelopmentDataError("observed development CSV is empty")
            digest.update(header)
            parser_input.write(header)
            byte_count += len(header)
            if _record_body(header, "observed development CSV header") != expected_header:
                raise DevelopmentDataError(
                    "observed development CSV schema or field order changed"
                )
            for raw_line in handle:
                digest.update(raw_line)
                parser_input.write(raw_line)
                byte_count += len(raw_line)
                row_count += 1
                record = _record_body(raw_line, "observed development CSV")
                timestamp = _raw_timestamp(record, "observed development CSV")
                if first_time is None:
                    first_time = timestamp
                last_time = timestamp
    except OSError as exc:
        parser_input.close()
        raise DevelopmentDataError(
            f"cannot scan observed development CSV: {path}"
        ) from exc
    except Exception:
        parser_input.close()
        raise

    checks = (
        (digest.hexdigest() == expected_sha256, "observed development SHA256 changed"),
        (byte_count == expected_byte_count, "observed development byte count changed"),
        (row_count == expected_row_count, "observed development row count changed"),
        (first_time == expected_first, "observed development first time changed"),
        (last_time == expected_last, "observed development last time changed"),
    )
    for valid, message in checks:
        if not valid:
            parser_input.close()
            raise DevelopmentDataError(message)
    parser_input.seek(0)
    return _ScanResult(
        parser_input=parser_input,
        prefix_sha256=expected_sha256,
        prefix_byte_count=byte_count,
    )


def _requested_columns(columns: Iterable[str] | None) -> tuple[str, ...]:
    if columns is None:
        return _ELIGIBLE_FIELDS
    if isinstance(columns, (str, bytes)):
        raise DevelopmentDataError("columns must be an iterable of field names")
    try:
        requested = tuple(columns)
    except TypeError as exc:
        raise DevelopmentDataError("columns must be an iterable of field names") from exc
    if not requested or any(type(column) is not str for column in requested):
        raise DevelopmentDataError("columns must contain field names")
    if len(set(requested)) != len(requested):
        raise DevelopmentDataError("columns must not contain duplicates")
    if "real_volume" in requested:
        raise DevelopmentDataError("real_volume is scientifically ineligible")
    unknown = set(requested).difference(_ELIGIBLE_FIELDS)
    if unknown:
        raise DevelopmentDataError("requested columns are outside the eligible schema")
    if "time" not in requested:
        raise DevelopmentDataError("time is required for scientific row identity")
    return requested


def _parse_and_validate(
    parser_input: io.BytesIO,
    *,
    expected_row_count: int,
    expected_first_time: pd.Timestamp,
    expected_last_time: pd.Timestamp,
    folds: tuple[RollingFoldMetadata, ...],
) -> pd.DataFrame:
    dtype = {field: "float64" for field in _NUMERIC_FIELDS}
    dtype["time"] = "string"
    try:
        frame = pd.read_csv(
            parser_input,
            usecols=list(_ELIGIBLE_FIELDS),
            dtype=dtype,
            engine="c",
        )
    except (OSError, TypeError, ValueError, pd.errors.ParserError) as exc:
        raise DevelopmentDataError("development CSV prefix cannot be parsed") from exc
    if tuple(frame.columns) != _ELIGIBLE_FIELDS:
        raise DevelopmentDataError("parsed development schema changed")
    if len(frame) != expected_row_count:
        raise DevelopmentDataError("parsed development row count changed")
    try:
        frame["time"] = pd.to_datetime(
            frame["time"], format=_TIME_FORMAT, errors="raise"
        )
    except (TypeError, ValueError) as exc:
        raise DevelopmentDataError("development timestamps are invalid") from exc

    times = frame["time"]
    if times.isna().any() or times.duplicated().any() or not times.is_monotonic_increasing:
        raise DevelopmentDataError("development timestamps must be strictly increasing")
    on_grid = (
        times.dt.minute.mod(5).eq(0)
        & times.dt.second.eq(0)
        & times.dt.microsecond.eq(0)
    )
    if not bool(on_grid.all()):
        raise DevelopmentDataError("development timestamps must lie on the M5 grid")
    if times.iloc[0] != expected_first_time or times.iloc[-1] != expected_last_time:
        raise DevelopmentDataError("parsed development time boundary changed")

    timestamps = times.to_numpy(dtype="datetime64[ns]", copy=False)
    for fold in folds:
        windows = (
            ("train_is", fold.train_is),
            ("validation_oos", fold.validation_oos),
            ("test_oos", fold.test_oos),
        )
        for role, window in windows:
            start = window.start.to_datetime64()
            end = window.end.to_datetime64()
            start_index = int(np.searchsorted(timestamps, start, side="left"))
            end_index = int(np.searchsorted(timestamps, end, side="right"))
            start_present = (
                start_index < len(timestamps) and timestamps[start_index] == start
            )
            end_present = end_index > 0 and timestamps[end_index - 1] == end
            actual_row_count = end_index - start_index
            if (
                not start_present
                or not end_present
                or actual_row_count != window.row_count
            ):
                raise DevelopmentDataError(
                    f"{fold.fold_id}.{role} row count does not match development frame"
                )

    numeric = frame.loc[:, _NUMERIC_FIELDS].to_numpy(dtype=np.float64, copy=False)
    if not bool(np.isfinite(numeric).all()):
        raise DevelopmentDataError("development numeric fields must be finite")
    open_values = frame["open"].to_numpy(copy=False)
    high_values = frame["high"].to_numpy(copy=False)
    low_values = frame["low"].to_numpy(copy=False)
    close_values = frame["close"].to_numpy(copy=False)
    upper = np.maximum.reduce((open_values, low_values, close_values))
    lower = np.minimum.reduce((open_values, high_values, close_values))
    if not bool((high_values >= upper).all() and (low_values <= lower).all()):
        raise DevelopmentDataError("development OHLC envelope is invalid")
    if not bool((frame["spread"] >= 0).all()):
        raise DevelopmentDataError("development spread must be non-negative")
    if not bool((frame["tick_volume"] >= 0).all()):
        raise DevelopmentDataError("development tick_volume must be non-negative")
    return frame


class ObservedDevelopmentLoader:
    """Load only the Foundation-registered observed development prefix."""

    def __init__(self, repository_root: str | Path) -> None:
        self._root = Path(repository_root).resolve()
        self._data_manifest_path = self._root / "foundation" / "data.yaml"
        self._exposure_manifest_path = (
            self._root / "foundation" / "data_exposure.yaml"
        )

    def load(
        self,
        *,
        columns: Iterable[str] | None = None,
    ) -> ObservedDevelopmentData:
        requested = _requested_columns(columns)
        data_manifest = _load_yaml(self._data_manifest_path, "data manifest")
        exposure = _load_yaml(self._exposure_manifest_path, "data exposure manifest")
        if data_manifest.get("schema") != "data_foundation":
            raise DevelopmentDataError("unexpected data manifest schema")
        if exposure.get("schema") != "data_exposure_foundation":
            raise DevelopmentDataError("unexpected data exposure schema")

        processed = _mapping(data_manifest.get("processed"), "data.processed")
        source_path = _resolve_inside(
            self._root, processed.get("path"), "data.processed.path"
        )
        dataset_sha256 = _sha256(
            processed.get("sha256"), "data.processed.sha256"
        )
        source_row_count = _integer(
            processed.get("row_count"), "data.processed.row_count", positive=True
        )
        source_first_text = _ascii(
            processed.get("first_time"), "data.processed.first_time"
        )
        source_last_text = _ascii(
            processed.get("last_time"), "data.processed.last_time"
        )
        source_first_time = _timestamp(source_first_text, "data.processed.first_time")
        source_last_time = _timestamp(source_last_text, "data.processed.last_time")
        fields = tuple(_list(processed.get("fields"), "data.processed.fields"))
        if fields != _SOURCE_FIELDS:
            raise DevelopmentDataError("Foundation processed field schema changed")
        volume_semantics = _mapping(
            data_manifest.get("volume_semantics"), "data.volume_semantics"
        )
        real_volume = _mapping(
            volume_semantics.get("real_volume"), "data.volume_semantics.real_volume"
        )
        if real_volume.get("eligible") is not False:
            raise DevelopmentDataError("real_volume ineligibility is not preserved")

        split_spec = _mapping(data_manifest.get("split_artifact"), "data.split_artifact")
        split_path = _resolve_inside(
            self._root, split_spec.get("path"), "data.split_artifact.path"
        )
        split_sha256 = _sha256(
            split_spec.get("sha256"), "data.split_artifact.sha256"
        )
        if _hash_file(split_path, "rolling-window artifact") != split_sha256:
            raise DevelopmentDataError("rolling-window artifact SHA256 changed")
        split = _load_json(split_path, "rolling-window artifact")
        if split.get("schema") != "axiom_rift_rolling_windows_v1":
            raise DevelopmentDataError("unexpected rolling-window artifact schema")
        if split.get("source_base_frame") != processed.get("path"):
            raise DevelopmentDataError("rolling windows name a different base frame")

        observed = _mapping(
            exposure.get("observed_development_material"),
            "exposure.observed_development_material",
        )
        identity = _ascii(observed.get("identity"), "development material identity")
        identity_domain = _ascii(
            observed.get("identity_domain"), "development material identity domain"
        )
        identity_inputs = _mapping(
            observed.get("identity_inputs"), "development material identity inputs"
        )
        if identity != canonical_digest(domain=identity_domain, payload=identity_inputs):
            raise DevelopmentDataError("development material identity is invalid")
        if identity_inputs.get("dataset_sha256") != dataset_sha256:
            raise DevelopmentDataError("development material names a different dataset")
        if identity_inputs.get("split_artifact_sha256") != split_sha256:
            raise DevelopmentDataError("development material names different rolling windows")
        expected_fold_count = _integer(
            identity_inputs.get("observed_window_count"),
            "development material observed_window_count",
            positive=True,
        )
        development_last_text = _ascii(
            identity_inputs.get("last_observed_development_time"),
            "development material last time",
        )
        development_last_time = _timestamp(
            development_last_text, "development material last time"
        )
        if observed.get("may_be_relabelled_fresh") is not False:
            raise DevelopmentDataError("development exposure may not be relabelled fresh")

        quarantine = _mapping(exposure.get("quarantined_tail"), "exposure.quarantined_tail")
        if quarantine.get("scientific_raw_access_allowed") is not False:
            raise DevelopmentDataError("quarantine raw access must remain forbidden")
        quarantine_start_text = _ascii(
            quarantine.get("start"), "exposure.quarantined_tail.start"
        )
        quarantine_end_text = _ascii(
            quarantine.get("end"), "exposure.quarantined_tail.end"
        )
        quarantine_start = _timestamp(
            quarantine_start_text, "exposure.quarantined_tail.start"
        )
        quarantine_end = _timestamp(
            quarantine_end_text, "exposure.quarantined_tail.end"
        )
        if quarantine_end != source_last_time:
            raise DevelopmentDataError("quarantine end must equal the source last time")

        tail = _mapping(split.get("tail_holdout_partial"), "split.tail_holdout_partial")
        quarantined_row_count = _integer(
            tail.get("row_count"), "split.tail_holdout_partial.row_count", positive=True
        )
        if (
            _timestamp(tail.get("start"), "split.tail_holdout_partial.start")
            != quarantine_start
            or _timestamp(tail.get("end"), "split.tail_holdout_partial.end")
            != quarantine_end
        ):
            raise DevelopmentDataError("split tail and quarantine boundaries disagree")
        development_row_count = source_row_count - quarantined_row_count
        if development_row_count <= 0:
            raise DevelopmentDataError("quarantine consumes the complete source")

        folds = _folds(
            split,
            expected_count=expected_fold_count,
            source_first_time=source_first_time,
            development_last_time=development_last_time,
        )
        if "observed_development" in data_manifest:
            prefix = _exact_mapping(
                data_manifest.get("observed_development"),
                "data.observed_development",
                fields=_OBSERVED_DEVELOPMENT_FIELDS,
            )
            prefix_path = _resolve_observed_development_path(
                self._root, prefix.get("path")
            )
            prefix_sha256 = _sha256(
                prefix.get("sha256"), "data.observed_development.sha256"
            )
            prefix_byte_count = _integer(
                prefix.get("byte_count"),
                "data.observed_development.byte_count",
                positive=True,
            )
            prefix_row_count = _integer(
                prefix.get("row_count"),
                "data.observed_development.row_count",
                positive=True,
            )
            prefix_first_text = _ascii(
                prefix.get("first_time"), "data.observed_development.first_time"
            )
            prefix_last_text = _ascii(
                prefix.get("last_time"), "data.observed_development.last_time"
            )
            prefix_first_time = _timestamp(
                prefix_first_text, "data.observed_development.first_time"
            )
            prefix_last_time = _timestamp(
                prefix_last_text, "data.observed_development.last_time"
            )
            parent_dataset_sha256 = _sha256(
                prefix.get("parent_dataset_sha256"),
                "data.observed_development.parent_dataset_sha256",
            )
            prefix_split_sha256 = _sha256(
                prefix.get("split_artifact_sha256"),
                "data.observed_development.split_artifact_sha256",
            )
            derivation = _ascii(
                prefix.get("derivation"), "data.observed_development.derivation"
            )
            checks = (
                (
                    prefix_path != source_path,
                    "observed development must be distinct from the full processed source",
                ),
                (
                    parent_dataset_sha256 == dataset_sha256,
                    "observed development names a different parent dataset",
                ),
                (
                    prefix_split_sha256 == split_sha256,
                    "observed development names different rolling windows",
                ),
                (
                    prefix_row_count == development_row_count,
                    "observed development row count differs from the split boundary",
                ),
                (
                    prefix_first_time == source_first_time,
                    "observed development first time differs from the parent dataset",
                ),
                (
                    prefix_last_time == development_last_time,
                    "observed development last time differs from the exposure boundary",
                ),
                (
                    derivation == _OBSERVED_DEVELOPMENT_DERIVATION,
                    "observed development derivation differs",
                ),
            )
            for valid, message in checks:
                if not valid:
                    raise DevelopmentDataError(message)
            scan = _scan_observed_development(
                prefix_path,
                expected_sha256=prefix_sha256,
                expected_byte_count=prefix_byte_count,
                expected_fields=_SOURCE_FIELDS,
                expected_row_count=prefix_row_count,
                expected_first_time=prefix_first_text,
                expected_last_time=prefix_last_text,
            )
        else:
            scan = _scan_source(
                source_path,
                expected_sha256=dataset_sha256,
                expected_fields=_SOURCE_FIELDS,
                expected_row_count=source_row_count,
                development_row_count=development_row_count,
                expected_first_time=source_first_text,
                expected_development_last_time=development_last_text,
                expected_quarantine_start=quarantine_start_text,
                expected_source_last_time=source_last_text,
            )
        try:
            frame = _parse_and_validate(
                scan.parser_input,
                expected_row_count=development_row_count,
                expected_first_time=source_first_time,
                expected_last_time=development_last_time,
                folds=folds,
            )
        finally:
            scan.parser_input.close()
        selected = frame.loc[:, requested].copy()
        metadata = DevelopmentMetadata(
            material_identity=identity,
            dataset_sha256=dataset_sha256,
            split_artifact_sha256=split_sha256,
            development_prefix_sha256=scan.prefix_sha256,
            source_path=source_path,
            source_row_count=source_row_count,
            development_row_count=development_row_count,
            quarantined_row_count=quarantined_row_count,
            prefix_byte_count=scan.prefix_byte_count,
            first_time=source_first_time,
            last_development_time=development_last_time,
            quarantined_start=quarantine_start,
            quarantined_end=quarantine_end,
            source_last_time=source_last_time,
            source_fields=_SOURCE_FIELDS,
            fields=requested,
            folds=folds,
        )
        return ObservedDevelopmentData(frame=selected, metadata=metadata)


def load_observed_development(
    repository_root: str | Path,
    *,
    columns: Iterable[str] | None = None,
) -> ObservedDevelopmentData:
    """Convenience API for the quarantine-safe Foundation loader."""

    return ObservedDevelopmentLoader(repository_root).load(columns=columns)


__all__ = [
    "DevelopmentDataError",
    "DevelopmentMetadata",
    "ObservedDevelopmentData",
    "ObservedDevelopmentLoader",
    "RollingFoldMetadata",
    "WindowMetadata",
    "load_observed_development",
]
