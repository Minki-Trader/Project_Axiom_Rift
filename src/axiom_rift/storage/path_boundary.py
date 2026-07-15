"""Link-free local directory creation for security-sensitive artifacts."""

from __future__ import annotations

from pathlib import Path
import os
import stat


class PathBoundaryError(RuntimeError):
    """A local path cannot be created without crossing a link-like boundary."""


def _is_link_like(metadata: os.stat_result) -> bool:
    if stat.S_ISLNK(metadata.st_mode):
        return True
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(getattr(metadata, "st_file_attributes", 0) & reparse_flag)


def _regular_single_link_signature(
    metadata: os.stat_result,
) -> tuple[int, ...]:
    if (
        _is_link_like(metadata)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
    ):
        raise PathBoundaryError("artifact is not a regular single-link file")
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
        metadata.st_nlink,
    )


def _same_file_bytes(left: tuple[int, ...], right: tuple[int, ...]) -> bool:
    # Windows can report a different ctime through an fd than through the path
    # after atomic replacement.  Each observation mode must keep its own ctime
    # stable; the cross-mode comparison uses identity, size, mtime, and links.
    return left[:4] + left[5:] == right[:4] + right[5:]


def require_link_free_directory_chain(path: str | Path) -> None:
    """Require every existing component through the filesystem root to be a directory."""

    absolute = Path(os.path.abspath(path))
    for directory in (absolute, *absolute.parents):
        try:
            metadata = directory.lstat()
        except OSError as exc:
            raise PathBoundaryError("directory chain is unavailable") from exc
        if _is_link_like(metadata) or not stat.S_ISDIR(metadata.st_mode):
            raise PathBoundaryError("directory chain is link-like or invalid")


def ensure_link_free_directory_chain(path: str | Path) -> None:
    """Create missing components only below a freshly verified real directory.

    ``Path.mkdir(parents=True)`` can traverse an existing directory symlink before
    a caller gets a chance to validate the completed chain.  This routine walks
    upward first, rejects a link-like existing ancestor, and then creates and
    revalidates one component at a time.
    """

    absolute = Path(os.path.abspath(path))
    missing: list[Path] = []
    cursor = absolute
    while True:
        try:
            metadata = cursor.lstat()
        except FileNotFoundError:
            if cursor.parent == cursor:
                raise PathBoundaryError("directory chain has no existing root")
            missing.append(cursor)
            cursor = cursor.parent
            continue
        except OSError as exc:
            raise PathBoundaryError("directory chain is unavailable") from exc
        if _is_link_like(metadata) or not stat.S_ISDIR(metadata.st_mode):
            raise PathBoundaryError("directory chain is link-like or invalid")
        require_link_free_directory_chain(cursor)
        break

    for directory in reversed(missing):
        require_link_free_directory_chain(directory.parent)
        try:
            directory.mkdir()
        except FileExistsError:
            # A concurrent creator is acceptable only if it created the exact
            # real-directory component that this process was about to create.
            pass
        except OSError as exc:
            raise PathBoundaryError("directory component cannot be created") from exc
        require_link_free_directory_chain(directory)


def read_stable_regular_file(
    path: str | Path,
    *,
    max_bytes: int | None = None,
    missing_ok: bool = False,
) -> bytes | None:
    """Read one exact link-free file identity without reader-side creation."""

    if max_bytes is not None and (
        type(max_bytes) is not int or max_bytes < 0
    ):
        raise ValueError("stable file max_bytes must be a nonnegative integer")
    if type(missing_ok) is not bool:
        raise ValueError("stable file missing_ok must be boolean")
    artifact = Path(os.path.abspath(path))
    try:
        path_before = _regular_single_link_signature(artifact.lstat())
    except FileNotFoundError:
        if missing_ok:
            return None
        raise PathBoundaryError("artifact is unavailable") from None
    except PathBoundaryError:
        raise
    except OSError as exc:
        raise PathBoundaryError("artifact is unavailable") from exc

    try:
        require_link_free_directory_chain(artifact.parent)
        with artifact.open("rb") as handle:
            opened_before = _regular_single_link_signature(
                os.fstat(handle.fileno())
            )
            content = handle.read() if max_bytes is None else handle.read(max_bytes + 1)
            opened_after = _regular_single_link_signature(
                os.fstat(handle.fileno())
            )
        require_link_free_directory_chain(artifact.parent)
        path_after = _regular_single_link_signature(artifact.lstat())
    except PathBoundaryError:
        raise
    except OSError as exc:
        raise PathBoundaryError(
            "artifact changed or became unavailable while read"
        ) from exc
    if max_bytes is not None and len(content) > max_bytes:
        raise PathBoundaryError("artifact exceeds the byte limit")
    if (
        path_before != path_after
        or opened_before != opened_after
        or not _same_file_bytes(opened_after, path_after)
        or len(content) != path_after[2]
    ):
        raise PathBoundaryError("artifact changed while read")
    return content
