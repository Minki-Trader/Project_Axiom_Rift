"""Quarantine-safe observed-development inputs for external M5 sources.

Routine research opens only the immutable development-prefix artifacts named
here.  Full raw snapshots remain acquisition and maintenance inputs and are
never opened by this loader.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path, PurePosixPath
import stat
from typing import Iterable, Mapping
from uuid import uuid4

import numpy as np
import pandas as pd

from axiom_rift.core.identity import canonical_digest


_THIS_FILE = Path(__file__).resolve()
_TIME_FORMAT = "%Y.%m.%d %H:%M:%S"
_M5_NS = 300_000_000_000
_COLUMNS = (
    "time",
    "open",
    "high",
    "low",
    "close",
    "tick_volume",
    "spread",
    "real_volume",
)
_PARSED_COLUMNS = _COLUMNS
_PREFIX_LANE = PurePosixPath("data/processed/datasets")
_RAW_LANE = PurePosixPath("data/raw/mt5_bars/m5")


def _digest(value: str, name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA256 digest")
    return value


def _parse_time(value: str, name: str) -> pd.Timestamp:
    if type(value) is not str or not value.isascii():
        raise ValueError(f"{name} must be ASCII")
    try:
        result = pd.to_datetime(value, format=_TIME_FORMAT, errors="raise")
    except ValueError as exc:
        raise ValueError(f"{name} is invalid") from exc
    if (
        not isinstance(result, pd.Timestamp)
        or pd.isna(result)
        or result.tzinfo is not None
        or result.strftime(_TIME_FORMAT) != value
        or result.second != 0
        or result.minute % 5 != 0
    ):
        raise ValueError(f"{name} is off the M5 grid")
    return result


def _canonical_relative(
    value: str,
    lane: PurePosixPath,
    name: str,
) -> PurePosixPath:
    if type(value) is not str or not value or not value.isascii():
        raise ValueError(f"{name} must be non-empty ASCII")
    relative = PurePosixPath(value)
    if (
        any(
            character
            not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_./-"
            for character in value
        )
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.as_posix() != value
        or relative.parts[: len(lane.parts)] != lane.parts
        or len(relative.parts) <= len(lane.parts)
    ):
        raise ValueError(f"{name} must remain in its canonical repository lane")
    return relative


class ExternalObservedDevelopmentError(RuntimeError):
    """An external development prefix failed its closed data boundary."""


@dataclass(frozen=True, slots=True)
class ExternalObservedDevelopmentSpec:
    source_key: str
    raw_relative_path: str
    parent_raw_sha256: str
    prefix_relative_path: str
    prefix_sha256: str
    prefix_byte_count: int
    row_count: int
    first_time: str
    last_time: str
    columns: tuple[str, ...] = _COLUMNS

    def __post_init__(self) -> None:
        if (
            type(self.source_key) is not str
            or not self.source_key
            or any(
                character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
                for character in self.source_key
            )
        ):
            raise ValueError("source_key must use canonical uppercase key characters")
        _canonical_relative(self.raw_relative_path, _RAW_LANE, "raw path")
        _canonical_relative(
            self.prefix_relative_path, _PREFIX_LANE, "prefix path"
        )
        _digest(self.parent_raw_sha256, "parent raw SHA256")
        _digest(self.prefix_sha256, "prefix SHA256")
        if (
            type(self.prefix_byte_count) is not int
            or type(self.row_count) is not int
            or self.prefix_byte_count <= 0
            or self.row_count <= 0
        ):
            raise ValueError("prefix size and row count must be positive")
        if self.columns != _COLUMNS:
            raise ValueError("external observed-development schema differs")
        first = _parse_time(self.first_time, "first_time")
        last = _parse_time(self.last_time, "last_time")
        if first >= last:
            raise ValueError("external development time boundary is invalid")

    @property
    def material_identity(self) -> str:
        return canonical_digest(
            domain="external-observed-development-material",
            payload={
                "columns": list(self.columns),
                "first_time": self.first_time,
                "last_time": self.last_time,
                "parent_raw_sha256": self.parent_raw_sha256,
                "prefix_byte_count": self.prefix_byte_count,
                "prefix_path": self.prefix_relative_path,
                "prefix_sha256": self.prefix_sha256,
                "row_count": self.row_count,
                "source_key": self.source_key,
            },
        )

    def job_input_hashes(self) -> tuple[str, str]:
        """Exact prospective Job inputs; raw identity is not a substitute."""

        return tuple(sorted((self.material_identity, self.prefix_sha256)))


US30_OBSERVED_DEVELOPMENT_SPEC = ExternalObservedDevelopmentSpec(
    source_key="US30",
    raw_relative_path="data/raw/mt5_bars/m5/US30_M5_max.csv",
    parent_raw_sha256=(
        "6d638467069a756a7a3897b587ec16a4b9ff76df8718186c2a81905d6d0488d4"
    ),
    prefix_relative_path="data/processed/datasets/us30_m5_observed_development.csv",
    prefix_sha256=(
        "31f52daff78fd1f146e0f8949ffc8970ed1f0ed7f1c09d8f7289a4a99312177b"
    ),
    prefix_byte_count=36_960_535,
    row_count=560_690,
    first_time="2018.05.07 01:00:00",
    last_time="2026.04.30 23:55:00",
)

US500_OBSERVED_DEVELOPMENT_SPEC = ExternalObservedDevelopmentSpec(
    source_key="US500",
    raw_relative_path="data/raw/mt5_bars/m5/US500_M5_max.csv",
    parent_raw_sha256=(
        "0cffed5e030cc71dd8a5df798b67e156c92f6e905b663d836115e2ceb1c3a424"
    ),
    prefix_relative_path="data/processed/datasets/us500_m5_observed_development.csv",
    prefix_sha256=(
        "8925c4824b4d934fcee14cc944b8a25044973e9b93d6f6c678b284bff3e21f10"
    ),
    prefix_byte_count=33_985_391,
    row_count=560_619,
    first_time="2018.05.07 01:00:00",
    last_time="2026.04.30 23:55:00",
)

USDJPY_OBSERVED_DEVELOPMENT_SPEC = ExternalObservedDevelopmentSpec(
    source_key="USDJPY",
    raw_relative_path="data/raw/mt5_bars/m5/USDJPY_M5_fixed.csv",
    parent_raw_sha256=(
        "364d94e662e5ee53e1092d11629deb8461575f82510a5b02d40f9ad46aabfa4e"
    ),
    prefix_relative_path="data/processed/datasets/usdjpy_m5_observed_development.csv",
    prefix_sha256=(
        "8f45cdf7d56c7ceb6a6933f737f3b5d765e22d0f7fcd4a26e0ebaa851403b310"
    ),
    prefix_byte_count=36_187_114,
    row_count=595_993,
    first_time="2018.05.07 01:00:00",
    last_time="2026.04.30 23:55:00",
)

_SPECS: Mapping[str, ExternalObservedDevelopmentSpec] = {
    value.source_key: value
    for value in (
        US30_OBSERVED_DEVELOPMENT_SPEC,
        US500_OBSERVED_DEVELOPMENT_SPEC,
        USDJPY_OBSERVED_DEVELOPMENT_SPEC,
    )
}


@dataclass(frozen=True, slots=True)
class ExternalObservedDevelopmentMetadata:
    source_key: str
    parent_raw_sha256: str
    development_prefix_sha256: str
    material_identity: str
    prefix_byte_count: int
    development_row_count: int
    first_time: pd.Timestamp
    last_time: pd.Timestamp
    source_path: Path

    @property
    def raw_sha256(self) -> str:
        """Compatibility alias for acquisition identity only."""

        return self.parent_raw_sha256


@dataclass(frozen=True, slots=True)
class ExternalObservedDevelopment:
    frame: pd.DataFrame
    metadata: ExternalObservedDevelopmentMetadata


@dataclass(frozen=True, slots=True)
class ProspectiveExternalSourceJobBinding:
    source_key: str
    material_identity: str
    development_prefix_sha256: str
    loader_implementation_sha256: str

    def to_payload(self) -> dict[str, str]:
        return {
            "development_prefix_sha256": self.development_prefix_sha256,
            "loader_implementation_sha256": self.loader_implementation_sha256,
            "material_identity": self.material_identity,
            "schema": "prospective_external_source_job_binding.v1",
            "source_key": self.source_key,
        }


def _is_link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction is not None and is_junction())


def _reject_link_path(root: Path, candidate: Path, name: str) -> None:
    cursor = candidate
    while cursor != root:
        if _is_link_like(cursor):
            raise ExternalObservedDevelopmentError(
                f"{name} traverses a link-like path"
            )
        cursor = cursor.parent


def _confined_existing(
    root: Path,
    relative_text: str,
    lane: PurePosixPath,
    name: str,
) -> Path:
    try:
        relative = _canonical_relative(relative_text, lane, name)
    except ValueError as exc:
        raise ExternalObservedDevelopmentError(str(exc)) from exc
    candidate = root.joinpath(*relative.parts)
    _reject_link_path(root, candidate, name)
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ExternalObservedDevelopmentError(f"{name} is unavailable") from exc
    if resolved != candidate or not candidate.is_file():
        raise ExternalObservedDevelopmentError(
            f"{name} is not a confined regular file"
        )
    return candidate


def _regular_lstat(path: Path, name: str) -> os.stat_result:
    try:
        result = path.lstat()
    except OSError as exc:
        raise ExternalObservedDevelopmentError(f"{name} is unavailable") from exc
    if not stat.S_ISREG(result.st_mode):
        raise ExternalObservedDevelopmentError(f"{name} is not a regular file")
    return result


def _same_file_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev == right.st_dev
        and left.st_ino == right.st_ino
        and stat.S_IFMT(left.st_mode) == stat.S_IFMT(right.st_mode)
    )


def _prepare_parent(
    root: Path,
    relative_text: str,
    lane: PurePosixPath,
    name: str,
) -> Path:
    try:
        relative = _canonical_relative(relative_text, lane, name)
    except ValueError as exc:
        raise ExternalObservedDevelopmentError(str(exc)) from exc
    current = root
    for part in relative.parent.parts:
        current = current / part
        if current.exists():
            if _is_link_like(current) or not current.is_dir():
                raise ExternalObservedDevelopmentError(
                    f"{name} parent is link-like or non-directory"
                )
        else:
            try:
                current.mkdir()
            except OSError as exc:
                raise ExternalObservedDevelopmentError(
                    f"{name} parent cannot be created"
                ) from exc
        try:
            if current.resolve(strict=True) != current:
                raise ExternalObservedDevelopmentError(
                    f"{name} parent is not confined"
                )
        except OSError as exc:
            raise ExternalObservedDevelopmentError(
                f"{name} parent is unavailable"
            ) from exc
    destination = root.joinpath(*relative.parts)
    if _is_link_like(destination):
        raise ExternalObservedDevelopmentError(f"{name} is link-like")
    return destination


def _record_body(raw_line: bytes, name: str) -> bytes:
    body = raw_line[:-1] if raw_line.endswith(b"\n") else raw_line
    body = body[:-1] if body.endswith(b"\r") else body
    if not body:
        raise ExternalObservedDevelopmentError(f"{name} contains an empty row")
    return body


def _timestamp_bytes(record: bytes, name: str) -> bytes:
    stamp, separator, _ = record.partition(b",")
    if not separator or len(stamp) != 19:
        raise ExternalObservedDevelopmentError(
            f"{name} timestamp field boundary is invalid"
        )
    punctuation = {4: 46, 7: 46, 10: 32, 13: 58, 16: 58}
    if any(stamp[index] != expected for index, expected in punctuation.items()) or any(
        not 48 <= value <= 57
        for index, value in enumerate(stamp)
        if index not in punctuation
    ):
        raise ExternalObservedDevelopmentError(f"{name} timestamp is invalid")
    minute = 10 * (stamp[14] - 48) + stamp[15] - 48
    if stamp[17:19] != b"00" or minute >= 60 or minute % 5 != 0:
        raise ExternalObservedDevelopmentError(f"{name} timestamp is off the M5 grid")
    return stamp


def external_observed_development_spec(
    source_key: str,
) -> ExternalObservedDevelopmentSpec:
    try:
        return _SPECS[source_key]
    except (KeyError, TypeError) as exc:
        raise ExternalObservedDevelopmentError(
            "external observed-development source is not registered"
        ) from exc


def external_observed_development_loader_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def prospective_external_source_job_binding(
    source_key: str,
    *,
    input_hashes: Iterable[str],
) -> ProspectiveExternalSourceJobBinding:
    """Require the exact prefix as a prospective scientific Job input."""

    spec = external_observed_development_spec(source_key)
    inputs = tuple(input_hashes)
    try:
        for index, value in enumerate(inputs):
            _digest(value, f"Job input hash {index}")
    except ValueError as exc:
        raise ExternalObservedDevelopmentError(str(exc)) from exc
    if len(inputs) != len(set(inputs)) or inputs != tuple(sorted(inputs)):
        raise ExternalObservedDevelopmentError(
            "Job input hashes must be sorted and unique"
        )
    if spec.prefix_sha256 not in inputs or spec.material_identity not in inputs:
        raise ExternalObservedDevelopmentError(
            "prospective external-source Job omits its exact prefix binding"
        )
    return ProspectiveExternalSourceJobBinding(
        source_key=spec.source_key,
        material_identity=spec.material_identity,
        development_prefix_sha256=spec.prefix_sha256,
        loader_implementation_sha256=(
            external_observed_development_loader_implementation_sha256()
        ),
    )


def _scan_prefix(
    root: Path,
    path: Path,
    spec: ExternalObservedDevelopmentSpec,
    *,
    retain_bytes: bool = True,
) -> BytesIO | None:
    expected_header = b",".join(value.encode("ascii") for value in spec.columns)
    expected_first = spec.first_time.encode("ascii")
    expected_last = spec.last_time.encode("ascii")
    digest = sha256()
    parser_input = BytesIO() if retain_bytes else None
    byte_count = 0
    row_count = 0
    first: bytes | None = None
    previous: bytes | None = None
    try:
        _reject_link_path(root, path, f"{spec.source_key} prefix")
        if path.resolve(strict=True) != path:
            raise ExternalObservedDevelopmentError(
                f"{spec.source_key} prefix path is not confined"
            )
        path_before = _regular_lstat(path, f"{spec.source_key} prefix")
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or not _same_file_identity(path_before, before)
            ):
                raise ExternalObservedDevelopmentError(
                    f"{spec.source_key} prefix open identity differs"
                )
            header = handle.readline()
            if not header or _record_body(header, spec.source_key) != expected_header:
                raise ExternalObservedDevelopmentError(
                    f"{spec.source_key} prefix schema or field order differs"
                )
            digest.update(header)
            if parser_input is not None:
                parser_input.write(header)
            byte_count += len(header)
            for raw_line in handle:
                record = _record_body(raw_line, spec.source_key)
                stamp = _timestamp_bytes(record, spec.source_key)
                if previous is not None and stamp <= previous:
                    raise ExternalObservedDevelopmentError(
                        f"{spec.source_key} prefix timestamps are not strictly increasing"
                    )
                previous = stamp
                if first is None:
                    first = stamp
                digest.update(raw_line)
                if parser_input is not None:
                    parser_input.write(raw_line)
                byte_count += len(raw_line)
                row_count += 1
            after = os.fstat(handle.fileno())
        _reject_link_path(root, path, f"{spec.source_key} prefix")
        if path.resolve(strict=True) != path:
            raise ExternalObservedDevelopmentError(
                f"{spec.source_key} prefix path changed during scan"
            )
        path_after = _regular_lstat(path, f"{spec.source_key} prefix")
    except OSError as exc:
        if parser_input is not None:
            parser_input.close()
        raise ExternalObservedDevelopmentError(
            f"{spec.source_key} prefix cannot be scanned"
        ) from exc
    except Exception:
        if parser_input is not None:
            parser_input.close()
        raise
    checks = (
        (before.st_size == spec.prefix_byte_count, "file size"),
        (after.st_size == spec.prefix_byte_count, "file size after scan"),
        (before.st_mtime_ns == after.st_mtime_ns, "file mutation"),
        (_same_file_identity(before, after), "open file identity"),
        (_same_file_identity(path_before, path_after), "path identity"),
        (_same_file_identity(after, path_after), "final path identity"),
        (digest.hexdigest() == spec.prefix_sha256, "SHA256"),
        (byte_count == spec.prefix_byte_count, "byte count"),
        (row_count == spec.row_count, "row count"),
        (first == expected_first, "first time"),
        (previous == expected_last, "last time"),
    )
    for valid, label in checks:
        if not valid:
            if parser_input is not None:
                parser_input.close()
            raise ExternalObservedDevelopmentError(
                f"{spec.source_key} prefix {label} differs"
            )
    if parser_input is not None:
        parser_input.seek(0)
    return parser_input


def verify_external_observed_development_prefix_identity(
    repository_root: str | Path,
    source_key: str,
) -> ExternalObservedDevelopmentMetadata:
    """Verify exact physical prefix identity without parsing it a second time.

    This path is intended for Job declaration, start, and cached-success reuse.
    It validates confinement, link safety, schema, byte count, SHA-256, row count,
    timestamp order, and the exact first/last boundary.  Execution still uses
    :func:`load_external_observed_development` once for numeric/OHLC validation.
    """

    spec = external_observed_development_spec(source_key)
    root = Path(repository_root).resolve()
    path = _confined_existing(
        root,
        spec.prefix_relative_path,
        _PREFIX_LANE,
        f"{spec.source_key} observed-development prefix",
    )
    if _scan_prefix(root, path, spec, retain_bytes=False) is not None:
        raise AssertionError("identity-only prefix scan retained parser bytes")
    return ExternalObservedDevelopmentMetadata(
        source_key=spec.source_key,
        parent_raw_sha256=spec.parent_raw_sha256,
        development_prefix_sha256=spec.prefix_sha256,
        material_identity=spec.material_identity,
        prefix_byte_count=spec.prefix_byte_count,
        development_row_count=spec.row_count,
        first_time=pd.Timestamp(spec.first_time),
        last_time=pd.Timestamp(spec.last_time),
        source_path=path,
    )


def _parse_prefix(
    parser_input: BytesIO,
    spec: ExternalObservedDevelopmentSpec,
) -> pd.DataFrame:
    dtypes = {
        "time": "string",
        "open": "float64",
        "high": "float64",
        "low": "float64",
        "close": "float64",
        "tick_volume": "int64",
        "spread": "int64",
        "real_volume": "int64",
    }
    try:
        frame = pd.read_csv(
            parser_input,
            usecols=list(_PARSED_COLUMNS),
            dtype=dtypes,
            engine="c",
        )
    except (OSError, TypeError, ValueError, pd.errors.ParserError) as exc:
        raise ExternalObservedDevelopmentError(
            f"{spec.source_key} prefix cannot be parsed"
        ) from exc
    if tuple(frame.columns) != _PARSED_COLUMNS or len(frame) != spec.row_count:
        raise ExternalObservedDevelopmentError(
            f"{spec.source_key} parsed schema or row count differs"
        )
    try:
        frame["time"] = pd.to_datetime(
            frame["time"], format=_TIME_FORMAT, errors="raise"
        )
    except (TypeError, ValueError) as exc:
        raise ExternalObservedDevelopmentError(
            f"{spec.source_key} parsed timestamps are invalid"
        ) from exc
    time = frame["time"]
    time_ns = time.to_numpy(dtype="datetime64[ns]").astype("int64")
    prices = frame.loc[:, ("open", "high", "low", "close")].to_numpy(float)
    open_, high, low, close = prices.T
    if (
        time.isna().any()
        or time.duplicated().any()
        or not time.is_monotonic_increasing
        or pd.Timestamp(time.iloc[0]) != pd.Timestamp(spec.first_time)
        or pd.Timestamp(time.iloc[-1]) != pd.Timestamp(spec.last_time)
        or np.any(time_ns % _M5_NS != 0)
        or np.any(~np.isfinite(prices))
        or np.any(prices <= 0)
        or np.any(high < np.maximum.reduce((open_, low, close)))
        or np.any(low > np.minimum.reduce((open_, high, close)))
        or np.any(frame["tick_volume"].to_numpy(np.int64) < 0)
        or np.any(frame["spread"].to_numpy(np.int64) < 0)
        or np.any(frame["real_volume"].to_numpy(np.int64) < 0)
    ):
        raise ExternalObservedDevelopmentError(
            f"{spec.source_key} prefix violates time, OHLC, or volume invariants"
        )
    return frame


def load_external_observed_development(
    repository_root: str | Path,
    source_key: str,
    *,
    columns: Iterable[str] = ("time", "close"),
) -> ExternalObservedDevelopment:
    """Load one exact prefix without resolving or opening its raw parent."""

    spec = external_observed_development_spec(source_key)
    requested = tuple(columns)
    if (
        not requested
        or len(requested) != len(set(requested))
        or any(value not in _PARSED_COLUMNS for value in requested)
    ):
        raise ExternalObservedDevelopmentError(
            "requested external prefix columns are invalid"
        )
    root = Path(repository_root).resolve()
    path = _confined_existing(
        root,
        spec.prefix_relative_path,
        _PREFIX_LANE,
        f"{spec.source_key} observed-development prefix",
    )
    parser_input = _scan_prefix(root, path, spec)
    if parser_input is None:
        raise AssertionError("external prefix parser bytes were not retained")
    try:
        validated = _parse_prefix(parser_input, spec)
    finally:
        parser_input.close()
    return ExternalObservedDevelopment(
        frame=validated.loc[:, requested].copy(),
        metadata=ExternalObservedDevelopmentMetadata(
            source_key=spec.source_key,
            parent_raw_sha256=spec.parent_raw_sha256,
            development_prefix_sha256=spec.prefix_sha256,
            material_identity=spec.material_identity,
            prefix_byte_count=spec.prefix_byte_count,
            development_row_count=spec.row_count,
            first_time=pd.Timestamp(spec.first_time),
            last_time=pd.Timestamp(spec.last_time),
            source_path=path,
        ),
    )


def _hash_file(path: Path) -> str:
    digest = sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise ExternalObservedDevelopmentError(
            "immutable raw snapshot cannot be hashed"
        ) from exc
    return digest.hexdigest()


def publish_immutable_raw_snapshot(
    repository_root: str | Path,
    source_key: str,
    content: bytes,
) -> str:
    """Publish an exact acquisition snapshot without overwriting any path."""

    if type(content) is not bytes or not content:
        raise ExternalObservedDevelopmentError(
            "immutable raw snapshot content must be non-empty bytes"
        )
    spec = external_observed_development_spec(source_key)
    if sha256(content).hexdigest() != spec.parent_raw_sha256:
        raise ExternalObservedDevelopmentError(
            f"{spec.source_key} acquired raw SHA256 differs from its contract"
        )
    root = Path(repository_root).resolve()
    destination = _prepare_parent(
        root,
        spec.raw_relative_path,
        _RAW_LANE,
        f"{spec.source_key} immutable raw snapshot",
    )
    if destination.exists() or _is_link_like(destination):
        existing = _confined_existing(
            root,
            spec.raw_relative_path,
            _RAW_LANE,
            f"{spec.source_key} immutable raw snapshot",
        )
        if _hash_file(existing) != spec.parent_raw_sha256:
            raise ExternalObservedDevelopmentError(
                f"{spec.source_key} existing raw snapshot identity differs"
            )
        return "existing_exact"
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        try:
            with temporary.open("xb") as handle:
                written = handle.write(content)
                if written != len(content):
                    raise ExternalObservedDevelopmentError(
                        f"{spec.source_key} raw staging was short"
                    )
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise ExternalObservedDevelopmentError(
                f"{spec.source_key} raw staging failed"
            ) from exc
        if _hash_file(temporary) != spec.parent_raw_sha256:
            raise ExternalObservedDevelopmentError(
                f"{spec.source_key} staged raw snapshot identity differs"
            )
        try:
            os.link(temporary, destination)
        except FileExistsError:
            existing = _confined_existing(
                root,
                spec.raw_relative_path,
                _RAW_LANE,
                f"{spec.source_key} immutable raw snapshot",
            )
            if _hash_file(existing) != spec.parent_raw_sha256:
                raise ExternalObservedDevelopmentError(
                    f"{spec.source_key} concurrent raw snapshot identity differs"
                )
            return "existing_exact"
        except OSError as exc:
            raise ExternalObservedDevelopmentError(
                f"{spec.source_key} raw publication failed"
            ) from exc
        published = _confined_existing(
            root,
            spec.raw_relative_path,
            _RAW_LANE,
            f"{spec.source_key} immutable raw snapshot",
        )
        if _hash_file(published) != spec.parent_raw_sha256:
            raise ExternalObservedDevelopmentError(
                f"{spec.source_key} published raw snapshot identity differs"
            )
        return "materialized"
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


__all__ = [
    "ExternalObservedDevelopment",
    "ExternalObservedDevelopmentError",
    "ExternalObservedDevelopmentMetadata",
    "ExternalObservedDevelopmentSpec",
    "ProspectiveExternalSourceJobBinding",
    "US30_OBSERVED_DEVELOPMENT_SPEC",
    "US500_OBSERVED_DEVELOPMENT_SPEC",
    "USDJPY_OBSERVED_DEVELOPMENT_SPEC",
    "external_observed_development_loader_implementation_sha256",
    "external_observed_development_spec",
    "load_external_observed_development",
    "prospective_external_source_job_binding",
    "publish_immutable_raw_snapshot",
    "verify_external_observed_development_prefix_identity",
]
