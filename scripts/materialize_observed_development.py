#!/usr/bin/env python3
"""Materialize the Foundation development prefix without exposing tail values."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import sys
from typing import Mapping, Sequence
from uuid import uuid4

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = "data/processed/datasets/us100_m5_observed_development.csv"
DERIVATION = "exact_prefix_before_quarantined_tail"
SOURCE_FIELDS = (
    "time",
    "open",
    "high",
    "low",
    "close",
    "tick_volume",
    "spread",
    "real_volume",
)
OBSERVED_FIELDS = frozenset(
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


class MaterializationError(RuntimeError):
    """Raised before an unsafe or inconsistent prefix can be published."""


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if type(value) is not dict:
        raise MaterializationError(f"{name} must be a mapping")
    return value


def _ascii(value: object, name: str) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise MaterializationError(f"{name} must be a non-empty ASCII string")
    return value


def _integer(value: object, name: str, *, positive: bool = False) -> int:
    if type(value) is not int or value < (1 if positive else 0):
        qualifier = "positive" if positive else "non-negative"
        raise MaterializationError(f"{name} must be a {qualifier} integer")
    return value


def _digest(value: object, name: str) -> str:
    result = _ascii(value, name)
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise MaterializationError(f"{name} must be a lowercase SHA256 digest")
    return result


def _relative_path(value: object, name: str) -> PurePosixPath:
    text = _ascii(value, name)
    relative = PurePosixPath(text)
    if (
        any(
            character
            not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_./-"
            for character in text
        )
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.as_posix() != text
    ):
        raise MaterializationError(f"{name} must be a canonical repository path")
    return relative


def _is_link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction is not None and is_junction())


def _existing_file(root: Path, value: object, name: str) -> tuple[PurePosixPath, Path]:
    relative = _relative_path(value, name)
    candidate = root.joinpath(*relative.parts)
    cursor = candidate
    while cursor != root:
        if _is_link_like(cursor):
            raise MaterializationError(f"{name} traverses a link-like path")
        cursor = cursor.parent
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise MaterializationError(f"{name} is unavailable") from exc
    if resolved != candidate or not candidate.is_file():
        raise MaterializationError(f"{name} is not a confined regular file")
    return relative, candidate


def _output_file(root: Path, value: object) -> tuple[PurePosixPath, Path]:
    relative = _relative_path(value, "output")
    lane = PurePosixPath("data/processed/datasets")
    if (
        relative.parts[: len(lane.parts)] != lane.parts
        or len(relative.parts) <= len(lane.parts)
    ):
        raise MaterializationError("output must remain in the observed dataset lane")
    current = root
    for part in relative.parent.parts:
        current = current / part
        if current.exists():
            if _is_link_like(current) or not current.is_dir():
                raise MaterializationError("output parent is link-like or non-directory")
        else:
            current.mkdir()
        try:
            resolved = current.resolve(strict=True)
        except OSError as exc:
            raise MaterializationError("output parent is unavailable") from exc
        if resolved != current:
            raise MaterializationError("output parent is not confined")
    destination = root.joinpath(*relative.parts)
    if _is_link_like(destination):
        raise MaterializationError("output is link-like")
    return relative, destination


def _confined_output_file(root: Path, relative: PurePosixPath) -> Path:
    current = root
    for part in relative.parent.parts:
        current = current / part
        if _is_link_like(current) or not current.is_dir():
            raise MaterializationError("output parent is link-like or non-directory")
        try:
            resolved = current.resolve(strict=True)
        except OSError as exc:
            raise MaterializationError("output parent is unavailable") from exc
        if resolved != current:
            raise MaterializationError("output parent is not confined")
    destination = root.joinpath(*relative.parts)
    if _is_link_like(destination):
        raise MaterializationError("output is link-like")
    try:
        resolved = destination.resolve(strict=True)
    except OSError as exc:
        raise MaterializationError("output is unavailable") from exc
    if resolved != destination or not destination.is_file():
        raise MaterializationError("output is not a confined regular file")
    return destination


def _load_yaml(path: Path, name: str) -> Mapping[str, object]:
    try:
        value = yaml.safe_load(path.read_text(encoding="ascii"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise MaterializationError(f"cannot read {name}") from exc
    return _mapping(value, name)


def _load_json(path: Path, name: str) -> Mapping[str, object]:
    try:
        value = json.loads(path.read_text(encoding="ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MaterializationError(f"cannot read {name}") from exc
    return _mapping(value, name)


def _hash_file(path: Path, name: str) -> tuple[str, int]:
    digest = sha256()
    size = 0
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise MaterializationError(f"cannot hash {name}") from exc
    return digest.hexdigest(), size


def _record_body(raw_line: bytes, name: str) -> bytes:
    body = raw_line
    if body.endswith(b"\n"):
        body = body[:-1]
        if body.endswith(b"\r"):
            body = body[:-1]
    if not body:
        raise MaterializationError(f"{name} contains an empty CSV record")
    return body


def _timestamp(record: bytes, name: str) -> bytes:
    timestamp, separator, _ = record.partition(b",")
    if not separator or len(timestamp) != 19:
        raise MaterializationError(f"{name} has an invalid timestamp boundary")
    return timestamp


def _foundation_plan(root: Path, output: str) -> dict[str, object]:
    data = _load_yaml(root / "foundation" / "data.yaml", "data manifest")
    exposure = _load_yaml(
        root / "foundation" / "data_exposure.yaml", "data exposure manifest"
    )
    if data.get("schema") != "data_foundation":
        raise MaterializationError("unexpected data manifest schema")
    if exposure.get("schema") != "data_exposure_foundation":
        raise MaterializationError("unexpected data exposure manifest schema")

    processed = _mapping(data.get("processed"), "data.processed")
    source_relative, source = _existing_file(
        root, processed.get("path"), "data.processed.path"
    )
    dataset_sha256 = _digest(processed.get("sha256"), "data.processed.sha256")
    source_row_count = _integer(
        processed.get("row_count"), "data.processed.row_count", positive=True
    )
    first_time = _ascii(processed.get("first_time"), "data.processed.first_time")
    fields = processed.get("fields")
    if type(fields) is not list or tuple(fields) != SOURCE_FIELDS:
        raise MaterializationError("Foundation processed field schema changed")

    split_spec = _mapping(data.get("split_artifact"), "data.split_artifact")
    _, split_path = _existing_file(
        root, split_spec.get("path"), "data.split_artifact.path"
    )
    split_sha256 = _digest(
        split_spec.get("sha256"), "data.split_artifact.sha256"
    )
    observed_split_sha256, _ = _hash_file(split_path, "rolling-window artifact")
    if observed_split_sha256 != split_sha256:
        raise MaterializationError("rolling-window artifact SHA256 changed")
    split = _load_json(split_path, "rolling-window artifact")
    if split.get("schema") != "axiom_rift_rolling_windows_v1":
        raise MaterializationError("unexpected rolling-window artifact schema")
    if split.get("source_base_frame") != source_relative.as_posix():
        raise MaterializationError("rolling windows name a different base frame")
    tail = _mapping(split.get("tail_holdout_partial"), "split.tail_holdout_partial")
    tail_row_count = _integer(
        tail.get("row_count"), "split.tail_holdout_partial.row_count", positive=True
    )

    observed = _mapping(
        exposure.get("observed_development_material"),
        "exposure.observed_development_material",
    )
    identity_inputs = _mapping(
        observed.get("identity_inputs"), "development material identity inputs"
    )
    if identity_inputs.get("dataset_sha256") != dataset_sha256:
        raise MaterializationError("development material names a different dataset")
    if identity_inputs.get("split_artifact_sha256") != split_sha256:
        raise MaterializationError("development material names different rolling windows")
    last_time = _ascii(
        identity_inputs.get("last_observed_development_time"),
        "development material last time",
    )

    quarantine = _mapping(exposure.get("quarantined_tail"), "exposure.quarantined_tail")
    if quarantine.get("scientific_raw_access_allowed") is not False:
        raise MaterializationError("quarantine raw access must remain forbidden")
    if tail.get("start") != quarantine.get("start") or tail.get("end") != quarantine.get("end"):
        raise MaterializationError("split tail and quarantine boundaries disagree")

    development_row_count = source_row_count - tail_row_count
    if development_row_count <= 0:
        raise MaterializationError("quarantine consumes the complete source")
    output_relative, destination = _output_file(root, output)
    if destination == source:
        raise MaterializationError("output must differ from the full processed source")
    existing_observed: dict[str, object] | None = None
    if "observed_development" in data:
        existing = _mapping(
            data.get("observed_development"), "data.observed_development"
        )
        if set(existing) != OBSERVED_FIELDS:
            raise MaterializationError(
                "existing Foundation observed development fields differ"
            )
        existing_observed = dict(existing)
    return {
        "dataset_sha256": dataset_sha256,
        "destination": destination,
        "development_row_count": development_row_count,
        "existing_observed": existing_observed,
        "first_time": first_time,
        "last_time": last_time,
        "output": output_relative.as_posix(),
        "source": source,
        "source_row_count": source_row_count,
        "split_sha256": split_sha256,
    }


def _scan_to_temporary(plan: Mapping[str, object], temporary: Path) -> dict[str, object]:
    source = plan["source"]
    if not isinstance(source, Path):
        raise MaterializationError("materialization source is invalid")
    expected_header = b",".join(field.encode("ascii") for field in SOURCE_FIELDS)
    development_row_count = int(plan["development_row_count"])
    source_row_count = int(plan["source_row_count"])
    full_digest = sha256()
    prefix_digest = sha256()
    prefix_byte_count = 0
    row_count = 0
    first_time: bytes | None = None
    last_time: bytes | None = None
    try:
        with source.open("rb") as source_handle, temporary.open("xb") as target:
            before = os.fstat(source_handle.fileno())
            header = source_handle.readline()
            if not header:
                raise MaterializationError("processed CSV is empty")
            full_digest.update(header)
            prefix_digest.update(header)
            target.write(header)
            prefix_byte_count += len(header)
            if _record_body(header, "processed CSV header") != expected_header:
                raise MaterializationError("processed CSV schema or field order changed")
            for raw_line in source_handle:
                full_digest.update(raw_line)
                row_count += 1
                if row_count <= development_row_count:
                    record = _record_body(raw_line, "development CSV prefix")
                    timestamp = _timestamp(record, "development CSV prefix")
                    if first_time is None:
                        first_time = timestamp
                    last_time = timestamp
                    prefix_digest.update(raw_line)
                    target.write(raw_line)
                    prefix_byte_count += len(raw_line)
                # Quarantine rows are integrity-hashed and counted only.  Their
                # fields are never split, parsed, retained, or rendered.
            target.flush()
            os.fsync(target.fileno())
            after = os.fstat(source_handle.fileno())
    except OSError as exc:
        raise MaterializationError("cannot materialize observed development") from exc

    before_identity = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    checks = (
        (before_identity == after_identity, "processed source changed during materialization"),
        (row_count == source_row_count, "processed source row count changed"),
        (
            full_digest.hexdigest() == plan["dataset_sha256"],
            "processed source SHA256 changed",
        ),
        (
            first_time == str(plan["first_time"]).encode("ascii"),
            "development prefix first time changed",
        ),
        (
            last_time == str(plan["last_time"]).encode("ascii"),
            "development prefix last time changed",
        ),
    )
    for valid, message in checks:
        if not valid:
            raise MaterializationError(message)
    return {
        "path": plan["output"],
        "sha256": prefix_digest.hexdigest(),
        "byte_count": prefix_byte_count,
        "row_count": development_row_count,
        "first_time": plan["first_time"],
        "last_time": plan["last_time"],
        "parent_dataset_sha256": plan["dataset_sha256"],
        "split_artifact_sha256": plan["split_sha256"],
        "derivation": DERIVATION,
    }


def _publish_exact(
    root: Path,
    temporary: Path,
    destination: Path,
    observed: Mapping[str, object],
) -> str:
    expected_sha256 = str(observed["sha256"])
    expected_size = int(observed["byte_count"])
    relative = _relative_path(observed.get("path"), "observed development path")
    expected_destination = root.joinpath(*relative.parts)
    if destination != expected_destination:
        raise MaterializationError("output path differs during publication")
    if destination.exists() or _is_link_like(destination):
        existing = _confined_output_file(root, relative)
        actual_sha256, actual_size = _hash_file(existing, "existing output")
        if actual_sha256 != expected_sha256 or actual_size != expected_size:
            raise MaterializationError("existing output identity differs")
        return "existing_exact"
    try:
        os.link(temporary, destination)
    except FileExistsError:
        concurrent = _confined_output_file(root, relative)
        actual_sha256, actual_size = _hash_file(concurrent, "concurrent output")
        if actual_sha256 != expected_sha256 or actual_size != expected_size:
            raise MaterializationError("concurrent output identity differs")
        return "existing_exact"
    except OSError as exc:
        raise MaterializationError("cannot atomically publish observed development") from exc
    published = _confined_output_file(root, relative)
    actual_sha256, actual_size = _hash_file(published, "published output")
    if actual_sha256 != expected_sha256 or actual_size != expected_size:
        raise MaterializationError("published output identity differs")
    return "materialized"


def materialize(root: Path, *, output: str = DEFAULT_OUTPUT) -> dict[str, object]:
    repository_root = root.resolve()
    plan = _foundation_plan(repository_root, output)
    destination = plan["destination"]
    if not isinstance(destination, Path):
        raise MaterializationError("materialization destination is invalid")
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        observed = _scan_to_temporary(plan, temporary)
        if set(observed) != OBSERVED_FIELDS:
            raise MaterializationError("observed development metadata fields differ")
        existing = plan.get("existing_observed")
        if existing is not None and existing != observed:
            raise MaterializationError(
                "existing Foundation observed development binding differs"
            )
        status = _publish_exact(
            repository_root, temporary, destination, observed
        )
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return {
        "observed_development": observed,
        "schema": "observed_development_materialization.v1",
        "status": status,
        "tail_values_exposed": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Materialize the exact observed-development CSV prefix."
    )
    parser.add_argument("--repository-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        report = materialize(arguments.repository_root, output=arguments.output)
    except (MaterializationError, OSError) as exc:
        print(
            json.dumps(
                {
                    "error": str(exc),
                    "schema": "observed_development_materialization_error.v1",
                },
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            report,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
