#!/usr/bin/env python3
"""Materialize external observed-development prefixes without reading tails."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from typing import BinaryIO, Sequence
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from axiom_rift.research.external_observed_development import (  # noqa: E402
    ExternalObservedDevelopmentError,
    ExternalObservedDevelopmentSpec,
    _PREFIX_LANE,
    _RAW_LANE,
    _confined_existing,
    _is_link_like,
    _parse_prefix,
    _prepare_parent,
    _record_body,
    _scan_prefix,
    _timestamp_bytes,
    external_observed_development_spec,
    load_external_observed_development,
)


class ExternalDevelopmentMaterializationError(RuntimeError):
    """A maintenance-only external prefix publication failed closed."""


def _copy_exact_prefix(
    source: BinaryIO,
    target: BinaryIO,
    spec: ExternalObservedDevelopmentSpec,
) -> None:
    """Stop on the exact last prefix line without requesting the next line."""

    expected_header = b",".join(value.encode("ascii") for value in spec.columns)
    last_boundary = spec.last_time.encode("ascii")
    prefix_hash = sha256()
    byte_count = 0
    row_count = 0
    previous: bytes | None = None
    first: bytes | None = None
    header = source.readline()
    if not header or _record_body(header, spec.source_key) != expected_header:
        raise ExternalDevelopmentMaterializationError(
            f"{spec.source_key} raw schema or field order differs"
        )
    prefix_hash.update(header)
    if target.write(header) != len(header):
        raise ExternalDevelopmentMaterializationError(
            f"{spec.source_key} prefix header staging was short"
        )
    byte_count += len(header)
    matched = False
    while True:
        raw_line = source.readline()
        if not raw_line:
            break
        record = _record_body(raw_line, spec.source_key)
        stamp = _timestamp_bytes(record, spec.source_key)
        if previous is not None and stamp <= previous:
            raise ExternalDevelopmentMaterializationError(
                f"{spec.source_key} raw timestamps are not strictly increasing"
            )
        previous = stamp
        if first is None:
            first = stamp
        if stamp > last_boundary:
            raise ExternalDevelopmentMaterializationError(
                f"{spec.source_key} development boundary was not found"
            )
        prefix_hash.update(raw_line)
        if target.write(raw_line) != len(raw_line):
            raise ExternalDevelopmentMaterializationError(
                f"{spec.source_key} prefix row staging was short"
            )
        byte_count += len(raw_line)
        row_count += 1
        if stamp == last_boundary:
            checks = (
                (prefix_hash.hexdigest() == spec.prefix_sha256, "SHA256"),
                (byte_count == spec.prefix_byte_count, "byte count"),
                (row_count == spec.row_count, "row count"),
                (first == spec.first_time.encode("ascii"), "first time"),
            )
            for valid, label in checks:
                if not valid:
                    raise ExternalDevelopmentMaterializationError(
                        f"{spec.source_key} prefix {label} differs"
                    )
            matched = True
            break
    if not matched:
        raise ExternalDevelopmentMaterializationError(
            f"{spec.source_key} development boundary is absent"
        )


def _publish(
    root: Path,
    temporary: Path,
    destination: Path,
    spec: ExternalObservedDevelopmentSpec,
) -> str:
    if destination.exists() or _is_link_like(destination):
        load_external_observed_development(root, spec.source_key)
        return "existing_exact"
    try:
        os.link(temporary, destination)
    except FileExistsError:
        load_external_observed_development(root, spec.source_key)
        return "existing_exact"
    except OSError as exc:
        raise ExternalDevelopmentMaterializationError(
            f"{spec.source_key} prefix publication failed"
        ) from exc
    load_external_observed_development(root, spec.source_key)
    return "materialized"


def materialize_external_observed_development(
    repository_root: str | Path,
    source_key: str,
    *,
    destination_relative: str | None = None,
) -> dict[str, object]:
    root = Path(repository_root).resolve()
    spec = external_observed_development_spec(source_key)
    requested_destination = (
        spec.prefix_relative_path
        if destination_relative is None
        else destination_relative
    )
    if requested_destination != spec.prefix_relative_path:
        raise ExternalDevelopmentMaterializationError(
            f"{spec.source_key} destination differs from its registered prefix path"
        )
    destination = _prepare_parent(
        root,
        requested_destination,
        _PREFIX_LANE,
        f"{spec.source_key} observed-development prefix",
    )
    if destination.exists() or _is_link_like(destination):
        load_external_observed_development(root, spec.source_key)
        status = "existing_exact"
    else:
        source = _confined_existing(
            root,
            spec.raw_relative_path,
            _RAW_LANE,
            f"{spec.source_key} maintenance raw parent",
        )
        temporary = destination.with_name(
            f".{destination.name}.{uuid4().hex}.tmp"
        )
        try:
            try:
                with source.open(
                    "rb", buffering=0
                ) as source_handle, temporary.open("xb") as target:
                    before = os.fstat(source_handle.fileno())
                    _copy_exact_prefix(source_handle, target, spec)
                    target.flush()
                    os.fsync(target.fileno())
                    after = os.fstat(source_handle.fileno())
            except OSError as exc:
                raise ExternalDevelopmentMaterializationError(
                    f"{spec.source_key} prefix staging failed"
                ) from exc
            if (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ):
                raise ExternalDevelopmentMaterializationError(
                    f"{spec.source_key} raw parent changed during prefix staging"
                )
            parser_input = _scan_prefix(root, temporary, spec)
            if parser_input is None:
                raise AssertionError("materialized prefix parser bytes were not retained")
            try:
                _parse_prefix(parser_input, spec)
            finally:
                parser_input.close()
            status = _publish(root, temporary, destination, spec)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
    return {
        "observed_development": {
            "byte_count": spec.prefix_byte_count,
            "first_time": spec.first_time,
            "last_time": spec.last_time,
            "material_identity": spec.material_identity,
            "parent_raw_sha256": spec.parent_raw_sha256,
            "path": spec.prefix_relative_path,
            "row_count": spec.row_count,
            "sha256": spec.prefix_sha256,
            "source_key": spec.source_key,
        },
        "raw_parent_fully_hashed": False,
        "schema": "external_observed_development_materialization.v1",
        "status": status,
        "tail_line_requested_after_boundary": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Materialize exact external development-only CSV prefixes."
    )
    parser.add_argument("--repository-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument(
        "--source",
        action="append",
        choices=("US30", "US500", "USDJPY"),
        required=True,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        reports = [
            materialize_external_observed_development(
                arguments.repository_root,
                source_key,
            )
            for source_key in dict.fromkeys(arguments.source)
        ]
    except (
        ExternalDevelopmentMaterializationError,
        ExternalObservedDevelopmentError,
        OSError,
        ValueError,
    ) as exc:
        print(
            json.dumps(
                {
                    "error": str(exc),
                    "schema": "external_observed_development_materialization_error.v1",
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
            {
                "reports": reports,
                "schema": "external_observed_development_materialization_batch.v1",
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
