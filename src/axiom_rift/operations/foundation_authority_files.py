"""Stable path and file authority for Foundation inputs and contracts."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

from axiom_rift.storage.atomic_file import (
    AtomicFileError,
    replace_stable_regular_file,
)
from axiom_rift.storage.path_boundary import (
    PathBoundaryError,
    read_stable_regular_file,
)


class FoundationAuthorityFileError(RuntimeError):
    """A Foundation authority path or file identity is unsafe or unstable."""


def canonical_foundation_path(root: str | Path, relative: object) -> Path:
    """Map one exact canonical POSIX relative path without resolving links."""

    if type(relative) is not str or not relative or not relative.isascii():
        raise FoundationAuthorityFileError(
            "Foundation authority path must be non-empty ASCII"
        )
    if "\\" in relative:
        raise FoundationAuthorityFileError(
            "Foundation authority path must use canonical POSIX separators"
        )
    parsed = PurePosixPath(relative)
    if (
        parsed.is_absolute()
        or parsed.as_posix() != relative
        or not parsed.parts
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise FoundationAuthorityFileError(
            "Foundation authority path is not canonical and relative"
        )
    return Path(root).joinpath(*parsed.parts)


def read_foundation_file(root: str | Path, relative: object) -> bytes:
    """Read one exact regular single-link Foundation file snapshot."""

    path = canonical_foundation_path(root, relative)
    try:
        content = read_stable_regular_file(path)
    except PathBoundaryError as exc:
        raise FoundationAuthorityFileError(
            f"Foundation authority file is unsafe or unavailable: {relative}"
        ) from exc
    if content is None:
        raise FoundationAuthorityFileError(
            f"Foundation authority file is unavailable: {relative}"
        )
    return content


def hash_foundation_file(root: str | Path, relative: object) -> str:
    return sha256(read_foundation_file(root, relative)).hexdigest()


def replace_foundation_file(
    root: str | Path,
    relative: object,
    content: bytes,
    *,
    expected_current_sha256: str,
) -> None:
    """CAS-replace one exact bound Foundation file and verify final bytes."""

    path = canonical_foundation_path(root, relative)
    try:
        replace_stable_regular_file(
            path,
            content,
            require_existing=True,
            expected_current_sha256=expected_current_sha256,
        )
    except (AtomicFileError, TypeError, ValueError) as exc:
        raise FoundationAuthorityFileError(
            f"Foundation authority replacement failed: {relative}"
        ) from exc
    if hash_foundation_file(root, relative) != sha256(content).hexdigest():
        raise FoundationAuthorityFileError(
            f"Foundation authority replacement verification failed: {relative}"
        )


__all__ = [
    "FoundationAuthorityFileError",
    "canonical_foundation_path",
    "hash_foundation_file",
    "read_foundation_file",
    "replace_foundation_file",
]
