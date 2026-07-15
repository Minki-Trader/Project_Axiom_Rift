"""Prospectively bind observed-development bytes to Jobs that consume them."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path, PurePosixPath
import stat

import yaml

from axiom_rift.core.identity import canonical_digest


class ObservedDevelopmentBindingError(ValueError):
    """Foundation metadata cannot authorize an observed-development Job binding."""


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ObservedDevelopmentBindingError(f"{name} must be a mapping")
    return value


def _ascii(value: object, name: str) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ObservedDevelopmentBindingError(
            f"{name} must be non-empty ASCII"
        )
    return value


def _digest(value: object, name: str) -> str:
    digest = _ascii(value, name)
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ObservedDevelopmentBindingError(
            f"{name} must be a lowercase SHA-256 digest"
        )
    return digest


def _load_mapping(path: Path, name: str) -> Mapping[str, object]:
    if not path.is_file():
        raise ObservedDevelopmentBindingError(f"{name} is absent")
    try:
        value = yaml.safe_load(path.read_text(encoding="ascii"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ObservedDevelopmentBindingError(
            f"{name} cannot be read as ASCII YAML"
        ) from exc
    return _mapping(value, name)


def _is_link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction is not None and is_junction())


def _confined_prefix_path(
    *, authority_root: Path, relative_text: str
) -> Path:
    relative = PurePosixPath(relative_text)
    if (
        relative.is_absolute()
        or relative.as_posix() != relative_text
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ObservedDevelopmentBindingError(
            "observed development prefix path is not canonical"
        )
    candidate = authority_root.joinpath(*relative.parts)
    cursor = candidate
    while cursor != authority_root:
        if _is_link_like(cursor):
            raise ObservedDevelopmentBindingError(
                "observed development prefix path traverses a link-like path"
            )
        cursor = cursor.parent
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ObservedDevelopmentBindingError(
            "observed development prefix path is unavailable"
        ) from exc
    if resolved != candidate or not candidate.is_file():
        raise ObservedDevelopmentBindingError(
            "observed development prefix path is not a confined regular file"
        )
    return candidate


def _same_open_file(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        stat.S_ISREG(left.st_mode)
        and stat.S_ISREG(right.st_mode)
        and left.st_dev == right.st_dev
        and left.st_ino == right.st_ino
        and left.st_size == right.st_size
        and left.st_mtime_ns == right.st_mtime_ns
    )


@dataclass(frozen=True, slots=True)
class ObservedDevelopmentJobBinding:
    """Exact Foundation material and prefix identities consumed by one Job."""

    material_identity: str
    observed_development_sha256: str
    parent_dataset_sha256: str
    split_artifact_sha256: str

    def to_payload(self) -> dict[str, str]:
        return {
            "material_identity": self.material_identity,
            "observed_development_sha256": self.observed_development_sha256,
            "parent_dataset_sha256": self.parent_dataset_sha256,
            "schema": "observed_development_job_binding.v1",
            "split_artifact_sha256": self.split_artifact_sha256,
        }


def observed_development_job_binding(
    *,
    foundation_root: str | Path,
    input_hashes: Sequence[str],
) -> ObservedDevelopmentJobBinding | None:
    """Return a binding only when the Job names the registered material.

    This reads metadata only.  The quarantine-safe loader remains responsible
    for verifying and parsing the registered prefix bytes during execution.
    """

    root = Path(foundation_root)
    foundation = root if root.name == "foundation" else root / "foundation"
    exposure = _load_mapping(
        foundation / "data_exposure.yaml", "data exposure Foundation"
    )
    observed_material = _mapping(
        exposure.get("observed_development_material"),
        "data exposure observed_development_material",
    )
    material_identity = _digest(
        observed_material.get("identity"),
        "observed development material identity",
    )
    if material_identity not in input_hashes:
        return None

    if exposure.get("schema") != "data_exposure_foundation":
        raise ObservedDevelopmentBindingError(
            "unexpected data exposure Foundation schema"
        )
    if exposure.get("identity_profile") != "axiom_cjson_v1":
        raise ObservedDevelopmentBindingError(
            "unexpected data exposure identity profile"
        )
    identity_domain = _ascii(
        observed_material.get("identity_domain"),
        "observed development material identity domain",
    )
    identity_inputs = _mapping(
        observed_material.get("identity_inputs"),
        "observed development material identity inputs",
    )
    if material_identity != canonical_digest(
        domain=identity_domain, payload=dict(identity_inputs)
    ):
        raise ObservedDevelopmentBindingError(
            "observed development material identity is invalid"
        )

    data = _load_mapping(foundation / "data.yaml", "data Foundation")
    if data.get("schema") != "data_foundation":
        raise ObservedDevelopmentBindingError("unexpected data Foundation schema")
    processed = _mapping(data.get("processed"), "data processed material")
    split = _mapping(data.get("split_artifact"), "data split artifact")
    prefix = _mapping(
        data.get("observed_development"), "data observed development prefix"
    )
    parent_dataset_sha256 = _digest(
        processed.get("sha256"), "processed dataset SHA-256"
    )
    split_artifact_sha256 = _digest(
        split.get("sha256"), "split artifact SHA-256"
    )
    observed_development_sha256 = _digest(
        prefix.get("sha256"), "observed development prefix SHA-256"
    )
    prefix_parent = _digest(
        prefix.get("parent_dataset_sha256"),
        "observed development parent dataset SHA-256",
    )
    prefix_split = _digest(
        prefix.get("split_artifact_sha256"),
        "observed development split artifact SHA-256",
    )
    material_parent = _digest(
        identity_inputs.get("dataset_sha256"),
        "observed development material dataset SHA-256",
    )
    material_split = _digest(
        identity_inputs.get("split_artifact_sha256"),
        "observed development material split artifact SHA-256",
    )
    material_last_time = _ascii(
        identity_inputs.get("last_observed_development_time"),
        "observed development material last time",
    )
    prefix_last_time = _ascii(
        prefix.get("last_time"), "observed development prefix last time"
    )
    if not (
        parent_dataset_sha256 == prefix_parent == material_parent
        and split_artifact_sha256 == prefix_split == material_split
        and prefix_last_time == material_last_time
    ):
        raise ObservedDevelopmentBindingError(
            "observed development Foundation identities disagree"
        )
    if prefix.get("derivation") != "exact_prefix_before_quarantined_tail":
        raise ObservedDevelopmentBindingError(
            "observed development prefix derivation is invalid"
        )
    return ObservedDevelopmentJobBinding(
        material_identity=material_identity,
        observed_development_sha256=observed_development_sha256,
        parent_dataset_sha256=parent_dataset_sha256,
        split_artifact_sha256=split_artifact_sha256,
    )


def scientific_observed_development_job_binding(
    *,
    foundation_root: str | Path,
    input_hashes: Sequence[str],
    lineage_material_identity: str | None,
) -> ObservedDevelopmentJobBinding | None:
    """Bind observed inputs and reject a scientific lineage that omits them."""

    inputs = tuple(input_hashes)
    if lineage_material_identity is not None:
        lineage_identity = _digest(
            lineage_material_identity, "scientific lineage material identity"
        )
        if lineage_identity not in inputs:
            raise ObservedDevelopmentBindingError(
                "scientific Job omits its lineage material input"
            )
    binding = observed_development_job_binding(
        foundation_root=foundation_root,
        input_hashes=inputs,
    )
    return binding


def verify_observed_development_prefix_artifact(
    *,
    foundation_root: str | Path,
    binding: ObservedDevelopmentJobBinding,
) -> None:
    """Hash the registered prefix bytes before reusing observed-bound work.

    The check opens only the exact prefix path registered in ``data.yaml``.
    It does not parse rows or inspect the quarantined parent tail.
    """

    if not isinstance(binding, ObservedDevelopmentJobBinding):
        raise TypeError("binding must be an ObservedDevelopmentJobBinding")
    current = observed_development_job_binding(
        foundation_root=foundation_root,
        input_hashes=(binding.material_identity,),
    )
    if current != binding:
        raise ObservedDevelopmentBindingError(
            "observed development binding differs from current Foundation"
        )
    root = Path(foundation_root).resolve()
    foundation = root if root.name == "foundation" else root / "foundation"
    authority_root = foundation.parent
    data = _load_mapping(foundation / "data.yaml", "data Foundation")
    prefix = _mapping(
        data.get("observed_development"), "data observed development prefix"
    )
    relative_text = _ascii(
        prefix.get("path"), "observed development prefix path"
    )
    target = _confined_prefix_path(
        authority_root=authority_root,
        relative_text=relative_text,
    )
    byte_count = prefix.get("byte_count")
    if type(byte_count) is not int or byte_count < 0:
        raise ObservedDevelopmentBindingError(
            "observed development prefix byte count is invalid"
        )
    try:
        with target.open("rb") as handle:
            before = os.fstat(handle.fileno())
            path_before = os.stat(target, follow_symlinks=False)
            observed_hash = sha256()
            while chunk := handle.read(1024 * 1024):
                observed_hash.update(chunk)
            after = os.fstat(handle.fileno())
            path_after = os.stat(target, follow_symlinks=False)
        final_target = _confined_prefix_path(
            authority_root=authority_root,
            relative_text=relative_text,
        )
    except OSError as exc:
        raise ObservedDevelopmentBindingError(
            "observed development prefix cannot be read"
        ) from exc
    if (
        before.st_size != byte_count
        or after.st_size != byte_count
        or not _same_open_file(before, after)
        or not _same_open_file(before, path_before)
        or not _same_open_file(after, path_after)
        or final_target != target
        or _is_link_like(target)
        or observed_hash.hexdigest() != binding.observed_development_sha256
    ):
        raise ObservedDevelopmentBindingError(
            "observed development prefix bytes differ from Foundation"
        )


__all__ = [
    "ObservedDevelopmentBindingError",
    "ObservedDevelopmentJobBinding",
    "observed_development_job_binding",
    "scientific_observed_development_job_binding",
    "verify_observed_development_prefix_artifact",
]
