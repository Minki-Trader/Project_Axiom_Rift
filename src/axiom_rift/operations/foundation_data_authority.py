"""Typed proof for prospective Foundation development-data authority changes.

The proof is deliberately stronger than a manifest receipt.  It hashes the
registered raw source as opaque bytes, streams the registered parent dataset,
validates every observed-development timestamp and market row, and compares
every observed byte with the exact leading parent bytes.  Raw values are never
decoded or parsed.  Quarantined parent rows contribute only timestamps,
integrity hash, and row count; their market values are never parsed.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
from typing import Mapping

import yaml

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest


FOUNDATION_DATA_PATH = "foundation/data.yaml"
FOUNDATION_DATA_EXPOSURE_PATH = "foundation/data_exposure.yaml"
PROTECTED_FOUNDATION_DATA_PATHS = frozenset(
    {FOUNDATION_DATA_PATH, FOUNDATION_DATA_EXPOSURE_PATH}
)
_DERIVATION = "exact_prefix_before_quarantined_tail"
_IDENTITY_DOMAIN = "development-material"
_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
_INTEGRITY_SCOPE = (
    "validate_observed_values_compare_exact_prefix_stream_tail_timestamps_only"
)
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
_DATA_FIELDS = frozenset(
    {
        "schema",
        "status",
        "target",
        "raw",
        "processed",
        "observed_development",
        "coverage",
        "split_artifact",
        "quality_observations",
        "volume_semantics",
        "protection",
    }
)
_RAW_FIELDS = frozenset({"path", "sha256"})
_PROCESSED_FIELDS = frozenset(
    {"path", "sha256", "row_count", "first_time", "last_time", "fields"}
)
_OBSERVED_FIELDS = frozenset(
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
_COVERAGE_FIELDS = frozenset(
    {
        "path",
        "sha256",
        "blackout_boundaries",
        "review_boundaries",
        "timestamp_gaps",
    }
)
_SPLIT_FIELDS = frozenset({"path", "sha256"})
_IDENTITY_INPUT_FIELDS = frozenset(
    {
        "dataset_sha256",
        "split_artifact_sha256",
        "observed_window_count",
        "last_observed_development_time",
    }
)
_QUALITY_FIELDS = frozenset(
    {
        "duplicate_rows",
        "non_monotonic_rows",
        "off_grid_rows",
        "nonfinite_rows",
        "negative_spread_rows",
        "invalid_ohlc_rows",
        "raw_to_processed_row_mismatches",
        "zero_spread_rows",
    }
)
_VOLUME_FIELDS = frozenset({"tick_volume", "real_volume"})
_REAL_VOLUME_FIELDS = frozenset({"eligible", "nonzero_rows"})
_PROTECTION_FIELDS = frozenset(
    {"ignored_by_git", "recoverable_from_git", "recursive_cleanup_allowed"}
)
_EXPOSURE_FIELDS = frozenset(
    {
        "schema",
        "status",
        "identity_profile",
        "observed_development_material",
        "quarantined_tail",
        "forward_holdout",
        "restricted_confirmation",
        "sealed_ingestion",
    }
)
_MATERIAL_FIELDS = frozenset(
    {
        "identity",
        "identity_domain",
        "identity_inputs",
        "display_name_is_identity",
        "roles",
        "may_be_relabelled_fresh",
        "prior_global_multiplicity_floor",
    }
)
_ROLE_FIELDS = frozenset({"train", "calibration", "adaptive_development"})
_QUARANTINE_FIELDS = frozenset(
    {
        "start",
        "end",
        "status",
        "scientific_raw_access_allowed",
        "claim_use_allowed",
    }
)
_FORWARD_HOLDOUT_FIELDS = frozenset(
    {"starts_after", "status", "reveal_count", "permitted_reveals_max"}
)
_RESTRICTED_CONFIRMATION_FIELDS = frozenset(
    {
        "redesign_after_observation_reclassifies_surface_as_development",
        "reuse_as_untouched_confirmation_after_redesign",
    }
)
_SEALED_INGESTION_FIELDS = frozenset(
    {
        "engineering_hash_and_seal_allowed",
        "scientific_value_read_requires_one_time_permit",
        "ingestion_changes_reveal_count",
    }
)
_NUMBER_PATTERN = re.compile(
    rb"[+-]?(?:(?:[0-9]+(?:\.[0-9]*)?)|(?:\.[0-9]+))(?:[eE][+-]?[0-9]+)?"
)


class FoundationDataAuthorityError(ValueError):
    """A proposed Foundation data authority is not an exact derivation."""


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if type(value) is not dict:
        raise FoundationDataAuthorityError(f"{name} must be a mapping")
    return value


def _exact_mapping(
    value: object, name: str, *, fields: frozenset[str]
) -> Mapping[str, object]:
    result = _mapping(value, name)
    if set(result) != fields:
        raise FoundationDataAuthorityError(f"{name} fields differ")
    return result


def _ascii(value: object, name: str) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise FoundationDataAuthorityError(f"{name} must be non-empty ASCII")
    return value


def _digest(value: object, name: str) -> str:
    result = _ascii(value, name)
    if len(result) != 64 or any(
        character not in "0123456789abcdef" for character in result
    ):
        raise FoundationDataAuthorityError(
            f"{name} must be a lowercase SHA-256 digest"
        )
    return result


def _positive_integer(value: object, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise FoundationDataAuthorityError(f"{name} must be a positive integer")
    return value


def _nonnegative_integer(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise FoundationDataAuthorityError(
            f"{name} must be a non-negative integer"
        )
    return value


def _timestamp_text(value: object, name: str) -> str:
    result = _ascii(value, name)
    if (
        len(result) != 19
        or result[4] != "-"
        or result[7] != "-"
        or result[10] != " "
        or result[13] != ":"
        or result[16] != ":"
        or any(
            not character.isdigit()
            for index, character in enumerate(result)
            if index not in {4, 7, 10, 13, 16}
        )
    ):
        raise FoundationDataAuthorityError(
            f"{name} must use YYYY-MM-DD HH:MM:SS"
        )
    try:
        parsed = datetime.fromisoformat(result)
    except ValueError as exc:
        raise FoundationDataAuthorityError(
            f"{name} must use YYYY-MM-DD HH:MM:SS"
        ) from exc
    if parsed.strftime(_TIME_FORMAT) != result:
        raise FoundationDataAuthorityError(
            f"{name} must use canonical YYYY-MM-DD HH:MM:SS"
        )
    return result


def _parsed_timestamp(value: object, name: str) -> datetime:
    return datetime.fromisoformat(_timestamp_text(value, name))


def _document(content: bytes, name: str) -> Mapping[str, object]:
    if type(content) is not bytes:
        raise FoundationDataAuthorityError(f"{name} bytes are invalid")
    try:
        value = yaml.safe_load(content.decode("ascii"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise FoundationDataAuthorityError(
            f"{name} is not ASCII YAML"
        ) from exc
    return _mapping(value, name)


def _relative_path(value: object, name: str) -> PurePosixPath:
    text = _ascii(value, name)
    relative = PurePosixPath(text)
    if (
        relative.is_absolute()
        or relative.as_posix() != text
        or any(part in {"", ".", ".."} for part in relative.parts)
        or any(
            character
            not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_./-"
            for character in text
        )
    ):
        raise FoundationDataAuthorityError(f"{name} is not a canonical path")
    return relative


def _is_link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction is not None and is_junction())


def _regular_file(
    root: Path,
    value: object,
    name: str,
    *,
    required_lane: PurePosixPath | None = None,
) -> tuple[str, Path]:
    relative = _relative_path(value, name)
    if required_lane is not None and (
        relative.parts[: len(required_lane.parts)] != required_lane.parts
        or len(relative.parts) <= len(required_lane.parts)
    ):
        raise FoundationDataAuthorityError(f"{name} escapes its data lane")
    candidate = root.joinpath(*relative.parts)
    cursor = candidate
    while cursor != root:
        if _is_link_like(cursor):
            raise FoundationDataAuthorityError(f"{name} traverses a link-like path")
        cursor = cursor.parent
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise FoundationDataAuthorityError(f"{name} is unavailable") from exc
    if resolved != candidate or not candidate.is_file():
        raise FoundationDataAuthorityError(
            f"{name} is not a confined regular file"
        )
    return relative.as_posix(), candidate


def _read_stable_file(path: Path, name: str) -> bytes:
    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            content = handle.read()
            after = os.fstat(handle.fileno())
    except OSError as exc:
        raise FoundationDataAuthorityError(f"cannot read {name}") from exc
    if _file_identity(before) != _file_identity(after):
        raise FoundationDataAuthorityError(f"{name} changed while reading")
    return content


def _hash_stable_file(path: Path, name: str) -> tuple[str, int]:
    """Hash opaque bytes without decoding or parsing protected values."""

    digest = sha256()
    byte_count = 0
    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                byte_count += len(chunk)
            after = os.fstat(handle.fileno())
    except OSError as exc:
        raise FoundationDataAuthorityError(f"cannot hash {name}") from exc
    if _file_identity(before) != _file_identity(after):
        raise FoundationDataAuthorityError(f"{name} changed while hashing")
    if byte_count <= 0:
        raise FoundationDataAuthorityError(f"{name} is empty")
    return digest.hexdigest(), byte_count


def _file_identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)


def _record_body(raw_line: bytes, name: str) -> bytes:
    body = raw_line
    if body.endswith(b"\n"):
        body = body[:-1]
        if body.endswith(b"\r"):
            body = body[:-1]
    if not body:
        raise FoundationDataAuthorityError(f"{name} contains an empty record")
    return body


def _raw_timestamp(raw_line: bytes, name: str) -> bytes:
    timestamp, separator, _ = _record_body(raw_line, name).partition(b",")
    if not separator or len(timestamp) != 19:
        raise FoundationDataAuthorityError(f"{name} timestamp is invalid")
    return timestamp


def _observed_market_row(raw_line: bytes) -> tuple[bytes, bool, bool]:
    fields = _record_body(raw_line, "observed development").split(b",")
    if len(fields) != len(_SOURCE_FIELDS):
        raise FoundationDataAuthorityError(
            "observed development field count differs"
        )
    timestamp = fields[0]
    values: list[float] = []
    for name, field in zip(_SOURCE_FIELDS[1:], fields[1:], strict=True):
        if not _NUMBER_PATTERN.fullmatch(field):
            raise FoundationDataAuthorityError(
                f"observed development {name} is not canonical numeric text"
            )
        value = float(field)
        if not math.isfinite(value):
            raise FoundationDataAuthorityError(
                f"observed development {name} is nonfinite"
            )
        values.append(value)
    open_value, high_value, low_value, close_value = values[:4]
    tick_volume, spread, real_volume = values[4:]
    if min(open_value, high_value, low_value, close_value) <= 0:
        raise FoundationDataAuthorityError(
            "observed development OHLC prices are not strictly positive"
        )
    if not (
        low_value <= min(open_value, close_value)
        and max(open_value, close_value) <= high_value
    ):
        raise FoundationDataAuthorityError(
            "observed development OHLC envelope is invalid"
        )
    if tick_volume < 0 or spread < 0 or real_volume < 0:
        raise FoundationDataAuthorityError(
            "observed development volume or spread is negative"
        )
    return timestamp, spread == 0.0, real_volume != 0.0


def _validate_document_schema_and_policy(
    data: Mapping[str, object], exposure: Mapping[str, object]
) -> str:
    """Require the complete canonical document shapes and protected policies."""

    data = _exact_mapping(data, "Foundation data document", fields=_DATA_FIELDS)
    exposure = _exact_mapping(
        exposure,
        "Foundation data exposure document",
        fields=_EXPOSURE_FIELDS,
    )
    if (
        data.get("schema") != "data_foundation"
        or data.get("status") != "preserved_intake_observation"
        or data.get("target") != "FPMarkets_US100_M5"
        or exposure.get("schema") != "data_exposure_foundation"
        or exposure.get("status") != "binding_prior_exposure"
        or exposure.get("identity_profile") != "axiom_cjson_v1"
    ):
        raise FoundationDataAuthorityError(
            "Foundation data document identity or target differs"
        )

    raw = _exact_mapping(data.get("raw"), "data.raw", fields=_RAW_FIELDS)
    _relative_path(raw.get("path"), "data.raw.path")
    _digest(raw.get("sha256"), "data.raw.sha256")

    processed = _exact_mapping(
        data.get("processed"), "data.processed", fields=_PROCESSED_FIELDS
    )
    _relative_path(processed.get("path"), "data.processed.path")
    _digest(processed.get("sha256"), "data.processed.sha256")
    _positive_integer(processed.get("row_count"), "data.processed.row_count")
    _timestamp_text(processed.get("first_time"), "data.processed.first_time")
    _timestamp_text(processed.get("last_time"), "data.processed.last_time")
    fields = processed.get("fields")
    if type(fields) is not list or tuple(fields) != _SOURCE_FIELDS:
        raise FoundationDataAuthorityError("Foundation processed fields differ")

    observed = _exact_mapping(
        data.get("observed_development"),
        "data.observed_development",
        fields=_OBSERVED_FIELDS,
    )
    _relative_path(observed.get("path"), "data.observed_development.path")
    _digest(observed.get("sha256"), "data.observed_development.sha256")
    _positive_integer(
        observed.get("byte_count"), "data.observed_development.byte_count"
    )
    _positive_integer(
        observed.get("row_count"), "data.observed_development.row_count"
    )
    _timestamp_text(
        observed.get("first_time"), "data.observed_development.first_time"
    )
    _timestamp_text(
        observed.get("last_time"), "data.observed_development.last_time"
    )
    _digest(
        observed.get("parent_dataset_sha256"),
        "data.observed_development.parent_dataset_sha256",
    )
    _digest(
        observed.get("split_artifact_sha256"),
        "data.observed_development.split_artifact_sha256",
    )
    if observed.get("derivation") != _DERIVATION:
        raise FoundationDataAuthorityError(
            "observed development derivation policy differs"
        )

    coverage = _exact_mapping(
        data.get("coverage"), "data.coverage", fields=_COVERAGE_FIELDS
    )
    _relative_path(coverage.get("path"), "data.coverage.path")
    _digest(coverage.get("sha256"), "data.coverage.sha256")
    for name in (
        "blackout_boundaries",
        "review_boundaries",
        "timestamp_gaps",
    ):
        _nonnegative_integer(coverage.get(name), f"data.coverage.{name}")

    split = _exact_mapping(
        data.get("split_artifact"),
        "data.split_artifact",
        fields=_SPLIT_FIELDS,
    )
    _relative_path(split.get("path"), "data.split_artifact.path")
    _digest(split.get("sha256"), "data.split_artifact.sha256")

    quality = _exact_mapping(
        data.get("quality_observations"),
        "data.quality_observations",
        fields=_QUALITY_FIELDS,
    )
    for name in _QUALITY_FIELDS:
        _nonnegative_integer(
            quality.get(name), f"data.quality_observations.{name}"
        )

    volume = _exact_mapping(
        data.get("volume_semantics"),
        "data.volume_semantics",
        fields=_VOLUME_FIELDS,
    )
    real_volume = _exact_mapping(
        volume.get("real_volume"),
        "data.volume_semantics.real_volume",
        fields=_REAL_VOLUME_FIELDS,
    )
    _nonnegative_integer(
        real_volume.get("nonzero_rows"),
        "data.volume_semantics.real_volume.nonzero_rows",
    )
    if (
        volume.get("tick_volume") != "broker_tick_count_not_traded_volume"
        or real_volume.get("eligible") is not False
    ):
        raise FoundationDataAuthorityError("Foundation volume policy differs")

    protection = _exact_mapping(
        data.get("protection"),
        "data.protection",
        fields=_PROTECTION_FIELDS,
    )
    if (
        protection.get("ignored_by_git") is not True
        or protection.get("recoverable_from_git") is not False
        or protection.get("recursive_cleanup_allowed") is not False
    ):
        raise FoundationDataAuthorityError(
            "Foundation protected-data policy is weakened"
        )

    material = _exact_mapping(
        exposure.get("observed_development_material"),
        "exposure.observed_development_material",
        fields=_MATERIAL_FIELDS,
    )
    _digest(material.get("identity"), "material identity")
    if material.get("identity_domain") != _IDENTITY_DOMAIN:
        raise FoundationDataAuthorityError(
            "observed development material identity domain differs"
        )
    inputs = _exact_mapping(
        material.get("identity_inputs"),
        "material identity inputs",
        fields=_IDENTITY_INPUT_FIELDS,
    )
    _digest(inputs.get("dataset_sha256"), "material dataset SHA-256")
    _digest(inputs.get("split_artifact_sha256"), "material split SHA-256")
    _positive_integer(
        inputs.get("observed_window_count"), "material observed window count"
    )
    _timestamp_text(
        inputs.get("last_observed_development_time"),
        "material last observed development time",
    )
    roles = _exact_mapping(
        material.get("roles"), "material roles", fields=_ROLE_FIELDS
    )
    if (
        material.get("display_name_is_identity") is not False
        or any(value != "observed_development" for value in roles.values())
        or material.get("may_be_relabelled_fresh") is not False
    ):
        raise FoundationDataAuthorityError(
            "observed development role or relabel policy differs"
        )
    _positive_integer(
        material.get("prior_global_multiplicity_floor"),
        "material prior global multiplicity floor",
    )

    quarantine = _exact_mapping(
        exposure.get("quarantined_tail"),
        "exposure.quarantined_tail",
        fields=_QUARANTINE_FIELDS,
    )
    _timestamp_text(quarantine.get("start"), "exposure.quarantined_tail.start")
    _timestamp_text(quarantine.get("end"), "exposure.quarantined_tail.end")
    if (
        quarantine.get("status") != "quarantine_pending_access_audit"
        or quarantine.get("scientific_raw_access_allowed") is not False
        or quarantine.get("claim_use_allowed") is not False
    ):
        raise FoundationDataAuthorityError(
            "quarantine access, claim, or status policy differs"
        )

    forward = _exact_mapping(
        exposure.get("forward_holdout"),
        "exposure.forward_holdout",
        fields=_FORWARD_HOLDOUT_FIELDS,
    )
    _timestamp_text(
        forward.get("starts_after"), "exposure.forward_holdout.starts_after"
    )
    reveal_count = _nonnegative_integer(
        forward.get("reveal_count"), "exposure.forward_holdout.reveal_count"
    )
    permitted_reveals_max = _positive_integer(
        forward.get("permitted_reveals_max"),
        "exposure.forward_holdout.permitted_reveals_max",
    )
    if (
        forward.get("status") != "awaiting_future_data"
        or reveal_count != 0
        or permitted_reveals_max != 1
    ):
        raise FoundationDataAuthorityError("forward holdout policy differs")

    restricted = _exact_mapping(
        exposure.get("restricted_confirmation"),
        "exposure.restricted_confirmation",
        fields=_RESTRICTED_CONFIRMATION_FIELDS,
    )
    if (
        restricted.get(
            "redesign_after_observation_reclassifies_surface_as_development"
        )
        is not True
        or restricted.get("reuse_as_untouched_confirmation_after_redesign")
        is not False
    ):
        raise FoundationDataAuthorityError(
            "restricted-confirmation policy differs"
        )

    sealed = _exact_mapping(
        exposure.get("sealed_ingestion"),
        "exposure.sealed_ingestion",
        fields=_SEALED_INGESTION_FIELDS,
    )
    if (
        sealed.get("engineering_hash_and_seal_allowed") is not True
        or sealed.get("scientific_value_read_requires_one_time_permit")
        is not True
        or sealed.get("ingestion_changes_reveal_count") is not False
    ):
        raise FoundationDataAuthorityError("sealed-ingestion policy differs")

    policy_projection = {
        "data": {
            "processed_fields": list(fields),
            "protection": dict(protection),
            "schema": data["schema"],
            "status": data["status"],
            "target": data["target"],
            "volume": {
                "real_volume_eligible": real_volume["eligible"],
                "tick_volume": volume["tick_volume"],
            },
        },
        "exposure": {
            "forward_holdout": {
                "permitted_reveals_max": forward["permitted_reveals_max"],
                "reveal_count": forward["reveal_count"],
                "status": forward["status"],
            },
            "identity_profile": exposure["identity_profile"],
            "material": {
                "display_name_is_identity": material["display_name_is_identity"],
                "identity_domain": material["identity_domain"],
                "may_be_relabelled_fresh": material["may_be_relabelled_fresh"],
                "prior_global_multiplicity_floor": material[
                    "prior_global_multiplicity_floor"
                ],
                "roles": dict(roles),
            },
            "quarantined_tail": {
                "claim_use_allowed": quarantine["claim_use_allowed"],
                "scientific_raw_access_allowed": quarantine[
                    "scientific_raw_access_allowed"
                ],
                "status": quarantine["status"],
            },
            "restricted_confirmation": dict(restricted),
            "schema": exposure["schema"],
            "sealed_ingestion": dict(sealed),
            "status": exposure["status"],
        },
        "observed_derivation": observed["derivation"],
    }
    return canonical_digest(
        domain="foundation-data-non-derivation-policy",
        payload=policy_projection,
    )


@dataclass(frozen=True, slots=True)
class _RollingWindow:
    name: str
    start: datetime
    end: datetime
    row_count: int


def _rolling_windows(
    split: Mapping[str, object],
    *,
    expected_count: int,
    source_first_time: str,
    development_last_time: str,
) -> tuple[_RollingWindow, ...]:
    declared_count = _positive_integer(split.get("fold_count"), "split.fold_count")
    folds = split.get("folds")
    if (
        declared_count != expected_count
        or type(folds) is not list
        or len(folds) != expected_count
    ):
        raise FoundationDataAuthorityError(
            "rolling-window count differs from the material identity"
        )
    lower = _parsed_timestamp(source_first_time, "parent first time")
    upper = _parsed_timestamp(development_last_time, "development last time")
    seen_ids: set[str] = set()
    previous_test_end: datetime | None = None
    result: list[_RollingWindow] = []
    for ordinal, value in enumerate(folds):
        fold = _mapping(value, f"split.folds[{ordinal}]")
        fold_id = _ascii(fold.get("fold_id"), f"split.folds[{ordinal}].fold_id")
        if fold_id in seen_ids:
            raise FoundationDataAuthorityError("rolling fold ids are duplicated")
        seen_ids.add(fold_id)
        fold_windows: list[_RollingWindow] = []
        for role in ("train_is", "validation_oos", "test_oos"):
            window = _mapping(fold.get(role), f"{fold_id}.{role}")
            start = _parsed_timestamp(window.get("start"), f"{fold_id}.{role}.start")
            end = _parsed_timestamp(window.get("end"), f"{fold_id}.{role}.end")
            row_count = _positive_integer(
                window.get("row_count"), f"{fold_id}.{role}.row_count"
            )
            if start > end or start < lower or end > upper:
                raise FoundationDataAuthorityError(
                    f"{fold_id}.{role} lies outside observed development"
                )
            fold_windows.append(
                _RollingWindow(
                    name=f"{fold_id}.{role}",
                    start=start,
                    end=end,
                    row_count=row_count,
                )
            )
        train, validation, test = fold_windows
        if not (train.end < validation.start and validation.end < test.start):
            raise FoundationDataAuthorityError(
                f"{fold_id} windows are not ordered and disjoint"
            )
        if previous_test_end is not None and test.start <= previous_test_end:
            raise FoundationDataAuthorityError(
                "rolling test windows are not strictly non-overlapping"
            )
        previous_test_end = test.end
        result.extend(fold_windows)
    if not result or result[-1].end != upper:
        raise FoundationDataAuthorityError(
            "last rolling test window does not end at development boundary"
        )
    return tuple(result)


def _validate_foundation_supporting_metadata(
    *,
    root: Path,
    data: Mapping[str, object],
    parent_relative: str,
    parent_row_count: int,
) -> tuple[int, int]:
    quality = _exact_mapping(
        data.get("quality_observations"),
        "data.quality_observations",
        fields=_QUALITY_FIELDS,
    )
    for name in (
        "duplicate_rows",
        "non_monotonic_rows",
        "off_grid_rows",
        "nonfinite_rows",
        "negative_spread_rows",
        "invalid_ohlc_rows",
        "raw_to_processed_row_mismatches",
    ):
        if quality.get(name) != 0:
            raise FoundationDataAuthorityError(
                f"Foundation quality observation {name} is not clean"
            )
    declared_zero_spread_rows = _nonnegative_integer(
        quality.get("zero_spread_rows"), "data.quality_observations.zero_spread_rows"
    )
    if declared_zero_spread_rows > parent_row_count:
        raise FoundationDataAuthorityError(
            "Foundation zero-spread count exceeds the parent row count"
        )

    volume = _mapping(data.get("volume_semantics"), "data.volume_semantics")
    real_volume = _mapping(
        volume.get("real_volume"), "data.volume_semantics.real_volume"
    )
    declared_nonzero_real_volume_rows = _nonnegative_integer(
        real_volume.get("nonzero_rows"),
        "data.volume_semantics.real_volume.nonzero_rows",
    )
    if (
        volume.get("tick_volume") != "broker_tick_count_not_traded_volume"
        or real_volume.get("eligible") is not False
        or declared_nonzero_real_volume_rows > parent_row_count
    ):
        raise FoundationDataAuthorityError("Foundation volume semantics differ")

    protection = _mapping(data.get("protection"), "data.protection")
    if (
        protection.get("ignored_by_git") is not True
        or protection.get("recoverable_from_git") is not False
        or protection.get("recursive_cleanup_allowed") is not False
    ):
        raise FoundationDataAuthorityError(
            "Foundation protected-data policy is weakened"
        )

    coverage_spec = _exact_mapping(
        data.get("coverage"), "data.coverage", fields=_COVERAGE_FIELDS
    )
    _, coverage_path = _regular_file(
        root,
        coverage_spec.get("path"),
        "data.coverage.path",
        required_lane=PurePosixPath("data/processed/coverage_audits"),
    )
    coverage_sha256 = _digest(
        coverage_spec.get("sha256"), "data.coverage.sha256"
    )
    coverage_bytes = _read_stable_file(coverage_path, "coverage audit")
    if sha256(coverage_bytes).hexdigest() != coverage_sha256:
        raise FoundationDataAuthorityError("coverage audit SHA-256 differs")
    try:
        coverage = _mapping(
            json.loads(coverage_bytes.decode("ascii")), "coverage audit"
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FoundationDataAuthorityError("coverage audit is invalid") from exc
    blackout_count = _nonnegative_integer(
        coverage_spec.get("blackout_boundaries"),
        "data.coverage.blackout_boundaries",
    )
    review_count = _nonnegative_integer(
        coverage_spec.get("review_boundaries"),
        "data.coverage.review_boundaries",
    )
    _nonnegative_integer(
        coverage_spec.get("timestamp_gaps"), "data.coverage.timestamp_gaps"
    )
    blackouts = coverage.get("blackout_gaps")
    suspicious = coverage.get("suspicious_gaps")
    observed = _mapping(coverage.get("observed"), "coverage audit observed")
    if (
        coverage.get("schema") != "axiom_rift_clean_periods_v1"
        or coverage.get("source_base_frame") != parent_relative
        or type(blackouts) is not list
        or len(blackouts) != blackout_count
        or type(suspicious) is not list
        or len(suspicious) != blackout_count + review_count
        or observed.get("blackout_gap_count") != blackout_count
        or observed.get("flag_for_review_gap_count") != review_count
        or observed.get("suspicious_gap_count") != blackout_count + review_count
    ):
        raise FoundationDataAuthorityError(
            "coverage audit does not match its Foundation binding"
        )
    return declared_zero_spread_rows, declared_nonzero_real_volume_rows


@dataclass(frozen=True, slots=True)
class FoundationDataDerivationProof:
    """Canonical reconstruction proof for one prospective data authority."""

    data_document_sha256: str
    data_exposure_document_sha256: str
    raw_path: str
    raw_sha256: str
    raw_byte_count: int
    parent_path: str
    parent_sha256: str
    parent_byte_count: int
    parent_row_count: int
    observed_path: str
    observed_sha256: str
    observed_byte_count: int
    observed_row_count: int
    observed_first_time: str
    observed_last_time: str
    split_path: str
    split_sha256: str
    quarantined_row_count: int
    material_identity: str
    material_identity_domain: str
    observed_window_count: int
    non_derivation_policy_sha256: str

    def to_identity_payload(self) -> dict[str, object]:
        return {
            "data_document_sha256": self.data_document_sha256,
            "data_exposure_document_sha256": self.data_exposure_document_sha256,
            "derivation": _DERIVATION,
            "integrity_scope": _INTEGRITY_SCOPE,
            "non_derivation_policy_sha256": self.non_derivation_policy_sha256,
            "material": {
                "identity": self.material_identity,
                "identity_domain": self.material_identity_domain,
                "identity_inputs": {
                    "dataset_sha256": self.parent_sha256,
                    "last_observed_development_time": self.observed_last_time,
                    "observed_window_count": self.observed_window_count,
                    "split_artifact_sha256": self.split_sha256,
                },
            },
            "observed_development": {
                "byte_count": self.observed_byte_count,
                "first_time": self.observed_first_time,
                "last_time": self.observed_last_time,
                "path": self.observed_path,
                "row_count": self.observed_row_count,
                "sha256": self.observed_sha256,
            },
            "parent_dataset": {
                "byte_count": self.parent_byte_count,
                "path": self.parent_path,
                "row_count": self.parent_row_count,
                "sha256": self.parent_sha256,
            },
            "quarantined_row_count": self.quarantined_row_count,
            "quality_scope": (
                "observed_values_validated_full_parent_declared_counts_are_lower_bounds"
            ),
            "raw_source": {
                "byte_count": self.raw_byte_count,
                "integrity_scope": "opaque_bytes_sha256_no_value_parse",
                "path": self.raw_path,
                "sha256": self.raw_sha256,
            },
            "schema": "foundation_data_derivation_proof.v1",
            "scientific_claim": "none",
            "split_artifact": {
                "path": self.split_path,
                "sha256": self.split_sha256,
            },
            "tail_values_exposed": False,
            "trial_delta": 0,
        }

    @property
    def identity(self) -> str:
        return "foundation-data-derivation:" + canonical_digest(
            domain="foundation-data-derivation",
            payload=self.to_identity_payload(),
        )

    def to_bytes(self) -> bytes:
        return canonical_bytes(self.to_identity_payload())

    @classmethod
    def from_bytes(cls, content: bytes) -> "FoundationDataDerivationProof":
        try:
            value = parse_canonical(content)
        except ValueError as exc:
            raise FoundationDataAuthorityError(
                "Foundation data derivation proof is not canonical"
            ) from exc
        payload = _mapping(value, "Foundation data derivation proof")
        if set(payload) != {
            "data_document_sha256",
            "data_exposure_document_sha256",
            "derivation",
            "integrity_scope",
            "material",
            "non_derivation_policy_sha256",
            "observed_development",
            "parent_dataset",
            "quarantined_row_count",
            "quality_scope",
            "raw_source",
            "schema",
            "scientific_claim",
            "split_artifact",
            "tail_values_exposed",
            "trial_delta",
        }:
            raise FoundationDataAuthorityError(
                "Foundation data derivation proof fields differ"
            )
        material = _mapping(payload.get("material"), "proof material")
        inputs = _exact_mapping(
            material.get("identity_inputs"),
            "proof material identity inputs",
            fields=_IDENTITY_INPUT_FIELDS,
        )
        parent = _mapping(payload.get("parent_dataset"), "proof parent")
        observed = _mapping(
            payload.get("observed_development"), "proof observed development"
        )
        raw = _mapping(payload.get("raw_source"), "proof raw source")
        split = _mapping(payload.get("split_artifact"), "proof split")
        if (
            payload.get("schema") != "foundation_data_derivation_proof.v1"
            or payload.get("derivation") != _DERIVATION
            or payload.get("integrity_scope") != _INTEGRITY_SCOPE
            or payload.get("quality_scope")
            != "observed_values_validated_full_parent_declared_counts_are_lower_bounds"
            or payload.get("scientific_claim") != "none"
            or payload.get("tail_values_exposed") is not False
            or payload.get("trial_delta") != 0
            or raw.get("integrity_scope")
            != "opaque_bytes_sha256_no_value_parse"
        ):
            raise FoundationDataAuthorityError(
                "Foundation data derivation proof semantics differ"
            )
        result = cls(
            data_document_sha256=_digest(
                payload.get("data_document_sha256"), "proof data document"
            ),
            data_exposure_document_sha256=_digest(
                payload.get("data_exposure_document_sha256"),
                "proof data exposure document",
            ),
            raw_path=_relative_path(
                raw.get("path"), "proof raw path"
            ).as_posix(),
            raw_sha256=_digest(raw.get("sha256"), "proof raw SHA-256"),
            raw_byte_count=_positive_integer(
                raw.get("byte_count"), "proof raw byte count"
            ),
            parent_path=_relative_path(
                parent.get("path"), "proof parent path"
            ).as_posix(),
            parent_sha256=_digest(parent.get("sha256"), "proof parent SHA-256"),
            parent_byte_count=_positive_integer(
                parent.get("byte_count"), "proof parent byte count"
            ),
            parent_row_count=_positive_integer(
                parent.get("row_count"), "proof parent row count"
            ),
            observed_path=_relative_path(
                observed.get("path"), "proof observed path"
            ).as_posix(),
            observed_sha256=_digest(
                observed.get("sha256"), "proof observed SHA-256"
            ),
            observed_byte_count=_positive_integer(
                observed.get("byte_count"), "proof observed byte count"
            ),
            observed_row_count=_positive_integer(
                observed.get("row_count"), "proof observed row count"
            ),
            observed_first_time=_timestamp_text(
                observed.get("first_time"), "proof observed first time"
            ),
            observed_last_time=_timestamp_text(
                observed.get("last_time"), "proof observed last time"
            ),
            split_path=_relative_path(
                split.get("path"), "proof split path"
            ).as_posix(),
            split_sha256=_digest(split.get("sha256"), "proof split SHA-256"),
            quarantined_row_count=_positive_integer(
                payload.get("quarantined_row_count"),
                "proof quarantined row count",
            ),
            material_identity=_digest(
                material.get("identity"), "proof material identity"
            ),
            material_identity_domain=_ascii(
                material.get("identity_domain"), "proof material identity domain"
            ),
            observed_window_count=_positive_integer(
                inputs.get("observed_window_count"),
                "proof observed window count",
            ),
            non_derivation_policy_sha256=_digest(
                payload.get("non_derivation_policy_sha256"),
                "proof non-derivation policy",
            ),
        )
        if (
            inputs.get("dataset_sha256") != result.parent_sha256
            or inputs.get("split_artifact_sha256") != result.split_sha256
            or inputs.get("last_observed_development_time")
            != result.observed_last_time
            or result.material_identity_domain != _IDENTITY_DOMAIN
            or result.to_bytes() != content
        ):
            raise FoundationDataAuthorityError(
                "Foundation data derivation proof is internally inconsistent"
            )
        return result


def foundation_data_derivation_binding(
    proof: FoundationDataDerivationProof,
) -> dict[str, str]:
    proof_bytes = proof.to_bytes()
    return {
        "data_document_sha256": proof.data_document_sha256,
        "data_exposure_document_sha256": proof.data_exposure_document_sha256,
        "material_identity": proof.material_identity,
        "proof_hash": sha256(proof_bytes).hexdigest(),
        "proof_id": proof.identity,
        "schema": "foundation_data_authority_derivation_binding.v1",
    }


def _document_material_binding(
    *,
    data_document: bytes,
    data_exposure_document: bytes,
    label: str,
) -> tuple[str, dict[str, object], str]:
    data = _document(data_document, f"{label} data document")
    exposure = _document(
        data_exposure_document, f"{label} data exposure document"
    )
    policy_sha256 = _validate_document_schema_and_policy(data, exposure)
    processed = _mapping(data.get("processed"), f"{label} data.processed")
    split = _mapping(data.get("split_artifact"), f"{label} data.split_artifact")
    observed = _exact_mapping(
        data.get("observed_development"),
        f"{label} data.observed_development",
        fields=_OBSERVED_FIELDS,
    )
    material = _mapping(
        exposure.get("observed_development_material"), f"{label} material"
    )
    domain = _ascii(material.get("identity_domain"), f"{label} identity domain")
    if domain != _IDENTITY_DOMAIN:
        raise FoundationDataAuthorityError(f"{label} identity domain differs")
    inputs = dict(
        _exact_mapping(
            material.get("identity_inputs"),
            f"{label} identity inputs",
            fields=_IDENTITY_INPUT_FIELDS,
        )
    )
    dataset_sha256 = _digest(
        processed.get("sha256"), f"{label} parent SHA-256"
    )
    split_sha256 = _digest(split.get("sha256"), f"{label} split SHA-256")
    last_time = _timestamp_text(
        inputs.get("last_observed_development_time"), f"{label} last time"
    )
    _positive_integer(inputs.get("observed_window_count"), f"{label} window count")
    identity = _digest(material.get("identity"), f"{label} material identity")
    if (
        inputs.get("dataset_sha256") != dataset_sha256
        or inputs.get("split_artifact_sha256") != split_sha256
        or observed.get("parent_dataset_sha256") != dataset_sha256
        or observed.get("split_artifact_sha256") != split_sha256
        or observed.get("last_time") != last_time
        or identity != canonical_digest(domain=domain, payload=inputs)
    ):
        raise FoundationDataAuthorityError(
            f"{label} material binding is inconsistent"
        )
    return identity, inputs, policy_sha256


def validate_foundation_data_identity_transition(
    *,
    predecessor_data_document: bytes,
    predecessor_data_exposure_document: bytes,
    successor_proof: FoundationDataDerivationProof,
) -> None:
    """Forbid identity resets and require real material changes to rekey."""

    (
        predecessor_identity,
        predecessor_inputs,
        predecessor_policy_sha256,
    ) = _document_material_binding(
        data_document=predecessor_data_document,
        data_exposure_document=predecessor_data_exposure_document,
        label="predecessor Foundation",
    )
    successor_inputs = {
        "dataset_sha256": successor_proof.parent_sha256,
        "split_artifact_sha256": successor_proof.split_sha256,
        "observed_window_count": successor_proof.observed_window_count,
        "last_observed_development_time": successor_proof.observed_last_time,
    }
    if successor_proof.material_identity_domain != _IDENTITY_DOMAIN:
        raise FoundationDataAuthorityError(
            "successor material identity domain differs"
        )
    if predecessor_inputs == successor_inputs:
        raise FoundationDataAuthorityError(
            "Foundation data migration requires changed material identity inputs"
        )
    if predecessor_identity == successor_proof.material_identity:
        raise FoundationDataAuthorityError(
            "material identity change does not match parent/split/window change"
        )
    if (
        predecessor_policy_sha256
        != successor_proof.non_derivation_policy_sha256
    ):
        raise FoundationDataAuthorityError(
            "Foundation non-derivation policy changed during data migration"
        )


def _stream_exact_derivation(
    *,
    parent_path: Path,
    observed_path: Path,
    expected_parent_sha256: str,
    expected_parent_row_count: int,
    expected_observed_sha256: str,
    expected_observed_byte_count: int,
    expected_observed_row_count: int,
    expected_first_time: str,
    expected_last_time: str,
    expected_parent_first_time: str,
    expected_parent_last_time: str,
    expected_quarantine_start: str,
    expected_quarantine_end: str,
    expected_header: bytes,
    rolling_windows: tuple[_RollingWindow, ...],
) -> tuple[int, int, int, int]:
    parent_digest = sha256()
    observed_digest = sha256()
    parent_bytes = 0
    observed_bytes = 0
    parent_rows = 0
    observed_rows = 0
    first_time: bytes | None = None
    last_time: bytes | None = None
    parent_first_time: bytes | None = None
    parent_last_time: bytes | None = None
    tail_first_time: bytes | None = None
    zero_spread_rows = 0
    nonzero_real_volume_rows = 0
    observed_timestamps: list[datetime] = []
    previous_parent_timestamp: datetime | None = None
    try:
        with parent_path.open("rb") as parent, observed_path.open("rb") as observed:
            parent_before = os.fstat(parent.fileno())
            observed_before = os.fstat(observed.fileno())
            parent_header = parent.readline()
            observed_header = observed.readline()
            if (
                not parent_header
                or parent_header != observed_header
                or _record_body(parent_header, "parent header") != expected_header
            ):
                raise FoundationDataAuthorityError(
                    "observed development header is not the exact parent header"
                )
            parent_digest.update(parent_header)
            observed_digest.update(observed_header)
            parent_bytes += len(parent_header)
            observed_bytes += len(observed_header)
            for ordinal in range(1, expected_parent_row_count + 1):
                parent_line = parent.readline()
                if not parent_line:
                    raise FoundationDataAuthorityError(
                        "parent dataset ended before its declared row count"
                    )
                parent_digest.update(parent_line)
                parent_bytes += len(parent_line)
                parent_rows += 1
                parent_timestamp = _raw_timestamp(parent_line, "parent dataset")
                try:
                    parsed_timestamp = _parsed_timestamp(
                        parent_timestamp.decode("ascii"), "parent dataset timestamp"
                    )
                except UnicodeDecodeError as exc:
                    raise FoundationDataAuthorityError(
                        "parent dataset timestamp is not ASCII"
                    ) from exc
                if (
                    parsed_timestamp.minute % 5 != 0
                    or parsed_timestamp.second != 0
                    or parsed_timestamp.microsecond != 0
                ):
                    raise FoundationDataAuthorityError(
                        "parent dataset timestamp is off the M5 grid"
                    )
                if (
                    previous_parent_timestamp is not None
                    and parsed_timestamp <= previous_parent_timestamp
                ):
                    raise FoundationDataAuthorityError(
                        "parent dataset timestamps are not strictly increasing"
                    )
                previous_parent_timestamp = parsed_timestamp
                if parent_first_time is None:
                    parent_first_time = parent_timestamp
                parent_last_time = parent_timestamp
                if ordinal == expected_observed_row_count + 1:
                    tail_first_time = parent_timestamp
                if ordinal > expected_observed_row_count:
                    continue
                observed_line = observed.readline()
                if not observed_line or observed_line != parent_line:
                    raise FoundationDataAuthorityError(
                        "observed development is not the exact parent prefix"
                    )
                observed_digest.update(observed_line)
                observed_bytes += len(observed_line)
                observed_rows += 1
                timestamp, zero_spread, nonzero_real_volume = _observed_market_row(
                    observed_line
                )
                if timestamp != parent_timestamp:
                    raise FoundationDataAuthorityError(
                        "observed and parent timestamps differ"
                    )
                zero_spread_rows += int(zero_spread)
                nonzero_real_volume_rows += int(nonzero_real_volume)
                observed_timestamps.append(parsed_timestamp)
                if first_time is None:
                    first_time = timestamp
                last_time = timestamp
            if parent.read(1) or observed.read(1):
                raise FoundationDataAuthorityError(
                    "parent or observed development has undeclared trailing bytes"
                )
            parent_after = os.fstat(parent.fileno())
            observed_after = os.fstat(observed.fileno())
    except OSError as exc:
        raise FoundationDataAuthorityError(
            "cannot verify the exact observed-development derivation"
        ) from exc
    checks = (
        (
            _file_identity(parent_before) == _file_identity(parent_after),
            "parent dataset changed during derivation verification",
        ),
        (
            _file_identity(observed_before) == _file_identity(observed_after),
            "observed development changed during derivation verification",
        ),
        (
            parent_digest.hexdigest() == expected_parent_sha256,
            "parent dataset SHA-256 differs",
        ),
        (
            parent_rows == expected_parent_row_count,
            "parent dataset row count differs",
        ),
        (
            parent_first_time == expected_parent_first_time.encode("ascii"),
            "parent dataset first time differs",
        ),
        (
            parent_last_time == expected_parent_last_time.encode("ascii"),
            "parent dataset last time differs",
        ),
        (
            tail_first_time == expected_quarantine_start.encode("ascii"),
            "actual quarantine start differs",
        ),
        (
            parent_last_time == expected_quarantine_end.encode("ascii"),
            "actual quarantine end differs",
        ),
        (
            observed_digest.hexdigest() == expected_observed_sha256,
            "observed development SHA-256 differs",
        ),
        (
            observed_bytes == expected_observed_byte_count,
            "observed development byte count differs",
        ),
        (
            observed_rows == expected_observed_row_count,
            "observed development row count differs",
        ),
        (
            first_time == expected_first_time.encode("ascii"),
            "observed development first time differs",
        ),
        (
            last_time == expected_last_time.encode("ascii"),
            "observed development last time differs",
        ),
    )
    for valid, message in checks:
        if not valid:
            raise FoundationDataAuthorityError(message)
    for window in rolling_windows:
        start_index = bisect_left(observed_timestamps, window.start)
        end_index = bisect_right(observed_timestamps, window.end)
        if (
            start_index >= len(observed_timestamps)
            or observed_timestamps[start_index] != window.start
            or end_index == 0
            or observed_timestamps[end_index - 1] != window.end
            or end_index - start_index != window.row_count
        ):
            raise FoundationDataAuthorityError(
                f"{window.name} row identity differs from observed development"
            )
    return (
        parent_bytes,
        observed_bytes,
        zero_spread_rows,
        nonzero_real_volume_rows,
    )


def build_foundation_data_derivation_proof(
    repository_root: str | Path,
    *,
    data_document: bytes,
    data_exposure_document: bytes,
) -> FoundationDataDerivationProof:
    """Recompute a proof from proposed authority bytes and actual data files."""

    root = Path(repository_root).resolve()
    data = _document(data_document, "Foundation data document")
    exposure = _document(
        data_exposure_document, "Foundation data exposure document"
    )
    non_derivation_policy_sha256 = _validate_document_schema_and_policy(
        data, exposure
    )

    raw = _exact_mapping(data.get("raw"), "data.raw", fields=_RAW_FIELDS)
    raw_relative, raw_path = _regular_file(
        root,
        raw.get("path"),
        "data.raw.path",
        required_lane=PurePosixPath("data/raw"),
    )
    raw_sha256 = _digest(raw.get("sha256"), "data.raw.sha256")
    actual_raw_sha256, raw_byte_count = _hash_stable_file(
        raw_path, "opaque raw source"
    )
    if actual_raw_sha256 != raw_sha256:
        raise FoundationDataAuthorityError(
            "raw source SHA-256 differs from its Foundation declaration"
        )

    processed = _exact_mapping(
        data.get("processed"), "data.processed", fields=_PROCESSED_FIELDS
    )
    parent_relative, parent_path = _regular_file(
        root,
        processed.get("path"),
        "data.processed.path",
        required_lane=PurePosixPath("data/processed/datasets"),
    )
    parent_sha256 = _digest(processed.get("sha256"), "data.processed.sha256")
    parent_row_count = _positive_integer(
        processed.get("row_count"), "data.processed.row_count"
    )
    parent_first_time = _timestamp_text(
        processed.get("first_time"), "data.processed.first_time"
    )
    parent_last_time = _timestamp_text(
        processed.get("last_time"), "data.processed.last_time"
    )
    fields = processed.get("fields")
    if type(fields) is not list or tuple(fields) != _SOURCE_FIELDS:
        raise FoundationDataAuthorityError("Foundation processed fields differ")
    (
        declared_zero_spread_rows,
        declared_nonzero_real_volume_rows,
    ) = _validate_foundation_supporting_metadata(
        root=root,
        data=data,
        parent_relative=parent_relative,
        parent_row_count=parent_row_count,
    )

    split_spec = _mapping(data.get("split_artifact"), "data.split_artifact")
    split_relative, split_path = _regular_file(
        root,
        split_spec.get("path"),
        "data.split_artifact.path",
        required_lane=PurePosixPath("data/processed/coverage_audits"),
    )
    split_sha256 = _digest(
        split_spec.get("sha256"), "data.split_artifact.sha256"
    )
    split_bytes = _read_stable_file(split_path, "rolling-window artifact")
    if sha256(split_bytes).hexdigest() != split_sha256:
        raise FoundationDataAuthorityError("rolling-window artifact SHA-256 differs")
    try:
        split = _mapping(
            json.loads(split_bytes.decode("ascii")),
            "rolling-window artifact",
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FoundationDataAuthorityError(
            "rolling-window artifact is invalid"
        ) from exc
    if (
        split.get("schema") != "axiom_rift_rolling_windows_v1"
        or split.get("source_base_frame") != parent_relative
    ):
        raise FoundationDataAuthorityError(
            "rolling-window artifact names another parent"
        )
    tail = _mapping(split.get("tail_holdout_partial"), "split.tail_holdout_partial")
    quarantined_row_count = _positive_integer(
        tail.get("row_count"), "split.tail_holdout_partial.row_count"
    )

    material = _mapping(
        exposure.get("observed_development_material"),
        "exposure.observed_development_material",
    )
    material_identity = _digest(material.get("identity"), "material identity")
    material_identity_domain = _ascii(
        material.get("identity_domain"), "material identity domain"
    )
    if material_identity_domain != _IDENTITY_DOMAIN:
        raise FoundationDataAuthorityError(
            "observed development material identity domain differs"
        )
    identity_inputs = _exact_mapping(
        material.get("identity_inputs"),
        "material identity inputs",
        fields=_IDENTITY_INPUT_FIELDS,
    )
    observed_window_count = _positive_integer(
        identity_inputs.get("observed_window_count"), "observed window count"
    )
    observed_last_time = _timestamp_text(
        identity_inputs.get("last_observed_development_time"),
        "material last observed development time",
    )
    if material.get("may_be_relabelled_fresh") is not False:
        raise FoundationDataAuthorityError(
            "observed development may not be relabelled fresh"
        )
    expected_material_identity = canonical_digest(
        domain=material_identity_domain, payload=dict(identity_inputs)
    )
    if (
        material_identity != expected_material_identity
        or identity_inputs.get("dataset_sha256") != parent_sha256
        or identity_inputs.get("split_artifact_sha256") != split_sha256
    ):
        raise FoundationDataAuthorityError(
            "observed development material identity is invalid"
        )

    quarantine = _mapping(
        exposure.get("quarantined_tail"), "exposure.quarantined_tail"
    )
    quarantine_start = _timestamp_text(
        quarantine.get("start"), "exposure.quarantined_tail.start"
    )
    quarantine_end = _timestamp_text(
        quarantine.get("end"), "exposure.quarantined_tail.end"
    )
    if (
        quarantine.get("scientific_raw_access_allowed") is not False
        or tail.get("start") != quarantine_start
        or tail.get("end") != quarantine_end
        or quarantine_end != parent_last_time
    ):
        raise FoundationDataAuthorityError(
            "quarantine and rolling-window tail boundaries disagree"
        )
    forward = _exact_mapping(
        exposure.get("forward_holdout"),
        "exposure.forward_holdout",
        fields=_FORWARD_HOLDOUT_FIELDS,
    )
    if forward.get("starts_after") != parent_last_time:
        raise FoundationDataAuthorityError(
            "forward holdout boundary differs from the parent last time"
        )
    if _parsed_timestamp(quarantine_start, "quarantine start") <= _parsed_timestamp(
        observed_last_time, "observed development last time"
    ):
        raise FoundationDataAuthorityError(
            "quarantine must start strictly after observed development"
        )
    rolling_windows = _rolling_windows(
        split,
        expected_count=observed_window_count,
        source_first_time=parent_first_time,
        development_last_time=observed_last_time,
    )

    observed = _exact_mapping(
        data.get("observed_development"),
        "data.observed_development",
        fields=_OBSERVED_FIELDS,
    )
    observed_relative, observed_path = _regular_file(
        root,
        observed.get("path"),
        "data.observed_development.path",
        required_lane=PurePosixPath("data/processed/datasets"),
    )
    if observed_path == parent_path:
        raise FoundationDataAuthorityError(
            "observed development must differ from its parent path"
        )
    observed_sha256 = _digest(
        observed.get("sha256"), "data.observed_development.sha256"
    )
    observed_byte_count = _positive_integer(
        observed.get("byte_count"), "data.observed_development.byte_count"
    )
    observed_row_count = _positive_integer(
        observed.get("row_count"), "data.observed_development.row_count"
    )
    observed_first_time = _timestamp_text(
        observed.get("first_time"), "data.observed_development.first_time"
    )
    manifest_observed_last_time = _timestamp_text(
        observed.get("last_time"), "data.observed_development.last_time"
    )
    if (
        observed.get("parent_dataset_sha256") != parent_sha256
        or observed.get("split_artifact_sha256") != split_sha256
        or observed.get("derivation") != _DERIVATION
        or observed_row_count != parent_row_count - quarantined_row_count
        or observed_first_time != parent_first_time
        or manifest_observed_last_time != observed_last_time
    ):
        raise FoundationDataAuthorityError(
            "observed development metadata is not parent/split derived"
        )

    (
        parent_byte_count,
        actual_observed_byte_count,
        observed_zero_spread_rows,
        observed_nonzero_real_volume_rows,
    ) = _stream_exact_derivation(
        parent_path=parent_path,
        observed_path=observed_path,
        expected_parent_sha256=parent_sha256,
        expected_parent_row_count=parent_row_count,
        expected_observed_sha256=observed_sha256,
        expected_observed_byte_count=observed_byte_count,
        expected_observed_row_count=observed_row_count,
        expected_first_time=observed_first_time,
        expected_last_time=observed_last_time,
        expected_parent_first_time=parent_first_time,
        expected_parent_last_time=parent_last_time,
        expected_quarantine_start=quarantine_start,
        expected_quarantine_end=quarantine_end,
        expected_header=b",".join(field.encode("ascii") for field in _SOURCE_FIELDS),
        rolling_windows=rolling_windows,
    )
    if actual_observed_byte_count != observed_byte_count:
        raise FoundationDataAuthorityError(
            "observed development byte count changed after verification"
        )
    if (
        observed_zero_spread_rows > declared_zero_spread_rows
        or observed_nonzero_real_volume_rows
        > declared_nonzero_real_volume_rows
    ):
        raise FoundationDataAuthorityError(
            "observed development exceeds declared full-parent quality counts"
        )
    return FoundationDataDerivationProof(
        data_document_sha256=sha256(data_document).hexdigest(),
        data_exposure_document_sha256=sha256(data_exposure_document).hexdigest(),
        raw_path=raw_relative,
        raw_sha256=raw_sha256,
        raw_byte_count=raw_byte_count,
        parent_path=parent_relative,
        parent_sha256=parent_sha256,
        parent_byte_count=parent_byte_count,
        parent_row_count=parent_row_count,
        observed_path=observed_relative,
        observed_sha256=observed_sha256,
        observed_byte_count=observed_byte_count,
        observed_row_count=observed_row_count,
        observed_first_time=observed_first_time,
        observed_last_time=observed_last_time,
        split_path=split_relative,
        split_sha256=split_sha256,
        quarantined_row_count=quarantined_row_count,
        material_identity=material_identity,
        material_identity_domain=material_identity_domain,
        observed_window_count=observed_window_count,
        non_derivation_policy_sha256=non_derivation_policy_sha256,
    )


def verify_foundation_data_derivation_proof(
    repository_root: str | Path,
    *,
    proof: FoundationDataDerivationProof,
    data_document: bytes,
    data_exposure_document: bytes,
) -> None:
    """Recompute and compare every proof field; caller declarations are inert."""

    recomputed = build_foundation_data_derivation_proof(
        repository_root,
        data_document=data_document,
        data_exposure_document=data_exposure_document,
    )
    if recomputed.to_identity_payload() != proof.to_identity_payload():
        raise FoundationDataAuthorityError(
            "Foundation data derivation proof no longer matches actual bytes"
        )


__all__ = [
    "FOUNDATION_DATA_EXPOSURE_PATH",
    "FOUNDATION_DATA_PATH",
    "PROTECTED_FOUNDATION_DATA_PATHS",
    "FoundationDataAuthorityError",
    "FoundationDataDerivationProof",
    "build_foundation_data_derivation_proof",
    "foundation_data_derivation_binding",
    "validate_foundation_data_identity_transition",
    "verify_foundation_data_derivation_proof",
]
