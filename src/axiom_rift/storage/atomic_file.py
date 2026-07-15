"""Identity-stable atomic replacement for security-sensitive local files."""

from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import stat
import tempfile

from axiom_rift.storage.path_boundary import (
    PathBoundaryError,
    ensure_link_free_directory_chain,
    read_stable_regular_file,
    require_link_free_directory_chain,
)


class AtomicFileError(RuntimeError):
    """One atomic replacement boundary changed or was link-like."""


_DEFAULT_MAX_EXISTING_BYTES = 16 * 1024 * 1024


def _regular_identity(metadata: os.stat_result) -> tuple[int, int]:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if (
        stat.S_ISLNK(metadata.st_mode)
        or bool(getattr(metadata, "st_file_attributes", 0) & reparse_flag)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
    ):
        raise AtomicFileError("atomic file is not a regular single-link file")
    return metadata.st_dev, metadata.st_ino


def _directory_identity(path: Path) -> tuple[int, int]:
    try:
        require_link_free_directory_chain(path)
        metadata = path.lstat()
    except (OSError, PathBoundaryError) as exc:
        raise AtomicFileError("atomic file directory is unavailable") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise AtomicFileError("atomic file parent is not a directory")
    return metadata.st_dev, metadata.st_ino


def _stable_snapshot(
    path: Path,
    *,
    max_bytes: int,
    missing_ok: bool,
) -> tuple[bytes, tuple[int, int, int, int, int, int]] | None:
    try:
        before = path.lstat()
    except FileNotFoundError:
        if missing_ok:
            return None
        raise AtomicFileError("atomic replacement target is unavailable") from None
    except OSError as exc:
        raise AtomicFileError("atomic replacement target is unavailable") from exc
    _regular_identity(before)
    try:
        content = read_stable_regular_file(path, max_bytes=max_bytes)
        after = path.lstat()
    except (OSError, PathBoundaryError) as exc:
        raise AtomicFileError("atomic replacement target changed while read") from exc
    if content is None:
        raise AtomicFileError("atomic replacement target is unavailable")
    before_signature = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
        before.st_nlink,
    )
    after_signature = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
        after.st_nlink,
    )
    if before_signature != after_signature:
        raise AtomicFileError("atomic replacement target identity changed")
    return content, before_signature


def _remove_exact_temporary(
    path: Path,
    *,
    identity: tuple[int, int],
    parent_identity: tuple[int, int],
) -> None:
    """Best-effort cleanup without unlinking a replacement directory entry."""

    try:
        if _directory_identity(path.parent) != parent_identity:
            return
        visible = path.lstat()
        if _regular_identity(visible) != identity:
            return
        if _directory_identity(path.parent) != parent_identity:
            return
        visible = path.lstat()
        if _regular_identity(visible) == identity:
            path.unlink()
    except (AtomicFileError, FileNotFoundError, OSError):
        pass


def _fsync_directory(path: Path) -> None:
    """Persist one renamed directory entry where directory fsync is supported."""

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        if os.name == "nt":
            # Windows does not expose portable directory fsync through os.open.
            return
        raise AtomicFileError("atomic directory cannot be opened for fsync") from exc
    try:
        os.fsync(descriptor)
    except OSError as exc:
        if os.name != "nt":
            raise AtomicFileError("atomic directory fsync failed") from exc
    finally:
        try:
            os.close(descriptor)
        except OSError:
            # A close failure cannot supersede publication or fsync evidence.
            pass


def _publish_missing_target(
    temporary: Path,
    target: Path,
    *,
    temporary_identity: tuple[int, int],
    parent_identity: tuple[int, int],
) -> None:
    """Publish a missing target without overwriting a concurrent creator."""

    if os.name == "nt":
        try:
            os.rename(temporary, target)
        except FileExistsError as exc:
            raise AtomicFileError(
                "atomic replacement target was created before publication"
            ) from exc
        return

    linked = False
    try:
        try:
            os.link(temporary, target, follow_symlinks=False)
        except FileExistsError as exc:
            raise AtomicFileError(
                "atomic replacement target was created before publication"
            ) from exc
        linked = True
        if _directory_identity(target.parent) != parent_identity:
            raise AtomicFileError("atomic replacement directory changed")
        temporary_metadata = temporary.lstat()
        target_metadata = target.lstat()
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        for metadata in (temporary_metadata, target_metadata):
            if (
                stat.S_ISLNK(metadata.st_mode)
                or bool(
                    getattr(metadata, "st_file_attributes", 0) & reparse_flag
                )
                or not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 2
                or (metadata.st_dev, metadata.st_ino) != temporary_identity
            ):
                raise AtomicFileError(
                    "atomic missing-target publication identity changed"
                )
        temporary.unlink()
        linked = False
    except AtomicFileError:
        raise
    except OSError as exc:
        raise AtomicFileError(
            "atomic missing-target publication failed"
        ) from exc
    finally:
        if linked:
            try:
                visible = target.lstat()
                if (
                    (visible.st_dev, visible.st_ino) == temporary_identity
                    and visible.st_nlink == 2
                    and not stat.S_ISLNK(visible.st_mode)
                    and stat.S_ISREG(visible.st_mode)
                ):
                    target.unlink()
            except (FileNotFoundError, OSError):
                pass


def _publish_stable_regular_file(
    path: str | Path,
    content: bytes,
    *,
    require_existing: bool = False,
    expected_current_sha256: str | None = None,
    max_existing_bytes: int = _DEFAULT_MAX_EXISTING_BYTES,
    skip_if_unchanged: bool,
    exclusive_missing_target: bool,
) -> bool:
    """Publish one exact file against its stable initial snapshot."""

    if type(content) is not bytes:
        raise TypeError("atomic replacement content must be bytes")
    if type(require_existing) is not bool:
        raise TypeError("atomic replacement require_existing must be boolean")
    if type(skip_if_unchanged) is not bool:
        raise TypeError("atomic replacement unchanged option must be boolean")
    if type(exclusive_missing_target) is not bool:
        raise TypeError("atomic replacement missing-target option must be boolean")
    if type(max_existing_bytes) is not int or max_existing_bytes < 0:
        raise ValueError("atomic replacement byte limit is invalid")
    if expected_current_sha256 is not None and (
        type(expected_current_sha256) is not str
        or len(expected_current_sha256) != 64
        or any(
            character not in "0123456789abcdef"
            for character in expected_current_sha256
        )
    ):
        raise ValueError("atomic replacement expected hash is invalid")

    target = Path(os.path.abspath(path))
    try:
        ensure_link_free_directory_chain(target.parent)
    except PathBoundaryError as exc:
        raise AtomicFileError("atomic replacement directory is unsafe") from exc
    parent_identity = _directory_identity(target.parent)
    initial = _stable_snapshot(
        target,
        max_bytes=max_existing_bytes,
        missing_ok=not require_existing,
    )
    if expected_current_sha256 is not None:
        if initial is None or sha256(initial[0]).hexdigest() != expected_current_sha256:
            raise AtomicFileError("atomic replacement source hash changed")
    if skip_if_unchanged and initial is not None and initial[0] == content:
        current = _stable_snapshot(
            target,
            max_bytes=max_existing_bytes,
            missing_ok=False,
        )
        if current != initial:
            raise AtomicFileError(
                "atomic replacement target changed before unchanged return"
            )
        if _directory_identity(target.parent) != parent_identity:
            raise AtomicFileError("atomic replacement directory changed")
        return False

    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
        )
    except OSError as exc:
        raise AtomicFileError("atomic temporary cannot be created") from exc
    temporary = Path(temporary_name)
    temporary_identity: tuple[int, int] | None = None
    descriptor_owned = True
    try:
        opened = os.fstat(descriptor)
        temporary_identity = _regular_identity(opened)
        if _regular_identity(temporary.lstat()) != temporary_identity:
            raise AtomicFileError("atomic temporary identity is invalid")
        handle = os.fdopen(descriptor, "wb")
        descriptor_owned = False
        with handle:
            if handle.write(content) != len(content):
                raise AtomicFileError("atomic temporary write was truncated")
            handle.flush()
            os.fsync(handle.fileno())
            final_opened = os.fstat(handle.fileno())
            if (
                _regular_identity(final_opened) != temporary_identity
                or final_opened.st_size != len(content)
            ):
                raise AtomicFileError("atomic temporary changed during write")

        if _directory_identity(target.parent) != parent_identity:
            raise AtomicFileError("atomic replacement directory changed")
        temporary_snapshot = _stable_snapshot(
            temporary,
            max_bytes=max(len(content), 1),
            missing_ok=False,
        )
        if (
            temporary_snapshot is None
            or temporary_snapshot[0] != content
            or temporary_snapshot[1][:2] != temporary_identity
        ):
            raise AtomicFileError("atomic temporary changed before publication")
        current = _stable_snapshot(
            target,
            max_bytes=max_existing_bytes,
            missing_ok=initial is None,
        )
        if (initial is None) != (current is None) or (
            initial is not None and current != initial
        ):
            raise AtomicFileError(
                "atomic replacement target changed before publication"
            )
        if _directory_identity(target.parent) != parent_identity:
            raise AtomicFileError("atomic replacement directory changed")
        if exclusive_missing_target and initial is None:
            _publish_missing_target(
                temporary,
                target,
                temporary_identity=temporary_identity,
                parent_identity=parent_identity,
            )
        else:
            os.replace(temporary, target)
        if _directory_identity(target.parent) != parent_identity:
            raise AtomicFileError(
                "atomic replacement directory changed after publication"
            )
        published = _stable_snapshot(
            target,
            max_bytes=max(len(content), 1),
            missing_ok=False,
        )
        if (
            published is None
            or published[0] != content
            or published[1][:2] != temporary_identity
        ):
            raise AtomicFileError("atomic publication identity or bytes differ")
        _fsync_directory(target.parent)
        return True
    except AtomicFileError:
        raise
    except OSError as exc:
        raise AtomicFileError("atomic replacement operation failed") from exc
    finally:
        if descriptor_owned:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary_identity is not None:
            _remove_exact_temporary(
                temporary,
                identity=temporary_identity,
                parent_identity=parent_identity,
            )


def replace_stable_regular_file(
    path: str | Path,
    content: bytes,
    *,
    require_existing: bool = False,
    expected_current_sha256: str | None = None,
    max_existing_bytes: int = _DEFAULT_MAX_EXISTING_BYTES,
) -> None:
    """Atomically replace one exact file without following aliases or links."""

    _publish_stable_regular_file(
        path,
        content,
        require_existing=require_existing,
        expected_current_sha256=expected_current_sha256,
        max_existing_bytes=max_existing_bytes,
        skip_if_unchanged=False,
        exclusive_missing_target=False,
    )


def publish_stable_regular_file_if_changed(
    path: str | Path,
    content: bytes,
    *,
    require_existing: bool = False,
    expected_current_sha256: str | None = None,
    max_existing_bytes: int = _DEFAULT_MAX_EXISTING_BYTES,
) -> bool:
    """Publish changed bytes after revalidating one stable target snapshot.

    Return ``False`` for an identity-stable identical target and ``True`` only
    after exact new bytes have been published.  Under the repository's
    cooperative writer lock, an existing target is checked immediately before
    atomic replacement.  Python exposes no portable identity-conditional
    replacement syscall, so an arbitrary non-cooperating writer in the final
    check-to-replace syscall window is outside this boundary.  An initially
    missing target uses exclusive publication and never overwrites a concurrent
    creator.
    """

    return _publish_stable_regular_file(
        path,
        content,
        require_existing=require_existing,
        expected_current_sha256=expected_current_sha256,
        max_existing_bytes=max_existing_bytes,
        skip_if_unchanged=True,
        exclusive_missing_target=True,
    )


__all__ = [
    "AtomicFileError",
    "publish_stable_regular_file_if_changed",
    "replace_stable_regular_file",
]
