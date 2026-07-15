"""Fail-closed publication for immutable reproducible-cache bytes."""

from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import re
import stat
import tempfile
import time


_THIS_FILE = Path(__file__).resolve()
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
_PORTABLE_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")
_WINDOWS_RESERVED_COMPONENTS = frozenset(
    {
        "aux",
        "con",
        "nul",
        "prn",
        *(f"com{ordinal}" for ordinal in range(1, 10)),
        *(f"lpt{ordinal}" for ordinal in range(1, 10)),
    }
)
_HANDOFF_ATTEMPTS = 50
_HANDOFF_SECONDS = 0.001


class ReproducibleCacheError(ValueError):
    """Raised when immutable cache publication cannot be proven safe."""


def reproducible_cache_implementation_sha256() -> str:
    """Return the exact source identity of this publication boundary."""

    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def _logical_path_parts(value: object) -> tuple[str, ...]:
    text = value
    if type(text) is not str or not text or not text.isascii():
        raise ReproducibleCacheError("artifact path must be non-empty ASCII")
    if len(text) > 1024 or "\\" in text or ":" in text:
        raise ReproducibleCacheError(
            "artifact path must use canonical POSIX spelling"
        )
    parts = tuple(text.split("/"))
    if (
        len(parts) < 2
        or any(part in {"", ".", ".."} for part in parts)
        or any(len(part) > 255 for part in parts)
    ):
        raise ReproducibleCacheError(
            "artifact path must be a normalized relative logical path"
        )
    for part in parts:
        if (
            _PORTABLE_COMPONENT.fullmatch(part) is None
            or part.endswith((".", " "))
            or part.split(".", 1)[0].casefold()
            in _WINDOWS_RESERVED_COMPONENTS
        ):
            raise ReproducibleCacheError(
                "artifact path contains a non-portable or reserved component"
            )
    return parts


def _is_reparse(metadata: os.stat_result) -> bool:
    return bool(
        _REPARSE_POINT
        and getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT
    )


def _directory_identity(path: Path) -> tuple[int, int, int]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ReproducibleCacheError(
            "artifact parent directory cannot be inspected"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or _is_reparse(metadata):
        raise ReproducibleCacheError(
            "artifact parent directory cannot be a link or reparse point"
        )
    if not stat.S_ISDIR(metadata.st_mode):
        raise ReproducibleCacheError("artifact parent must be a directory")
    return (
        metadata.st_dev,
        metadata.st_ino,
        stat.S_IFMT(metadata.st_mode),
    )


def _plain_output_root(value: str | Path) -> Path:
    if not isinstance(value, (str, Path)):
        raise ReproducibleCacheError("output root must be text or Path")
    raw = os.fspath(value)
    if type(raw) is not str or not raw:
        raise ReproducibleCacheError("output root must be non-empty")
    normalized = raw.replace("\\", "/")
    if any(part in {".", ".."} for part in normalized.split("/")):
        raise ReproducibleCacheError("output root must use canonical spelling")
    lexical = Path(raw)
    if not lexical.is_absolute():
        raise ReproducibleCacheError("output root must be absolute")
    lexical = lexical.absolute()
    chain = (*reversed(lexical.parents), lexical)
    for path in chain:
        _directory_identity(path)
    return lexical


def _prepare_plain_parent(
    root: Path,
    relative_parts: tuple[str, ...],
) -> tuple[Path, tuple[tuple[Path, tuple[int, int, int]], ...]]:
    chain: list[tuple[Path, tuple[int, int, int]]] = [
        (root, _directory_identity(root))
    ]
    current = root
    for part in relative_parts:
        current = current / part
        try:
            current.mkdir()
        except FileExistsError:
            pass
        except OSError as exc:
            raise ReproducibleCacheError(
                "artifact parent directory cannot be created"
            ) from exc
        chain.append((current, _directory_identity(current)))
    return current, tuple(chain)


def _verify_directory_chain(
    chain: tuple[tuple[Path, tuple[int, int, int]], ...],
) -> None:
    if any(_directory_identity(path) != identity for path, identity in chain):
        raise ReproducibleCacheError(
            "artifact parent directory identity changed during publication"
        )


def _file_identity(metadata: os.stat_result) -> tuple[int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        stat.S_IFMT(metadata.st_mode),
    )


def _file_snapshot(metadata: os.stat_result) -> tuple[object, ...]:
    return (
        *_file_identity(metadata),
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_nlink,
    )


class _ConcurrentPublishHandoff(Exception):
    pass


def _read_exact_file_snapshot(
    path: Path,
    content: bytes,
    *,
    expected_identity: tuple[int, int, int] | None = None,
) -> None:
    try:
        before = path.lstat()
    except OSError as exc:
        raise ReproducibleCacheError("published artifact cannot be inspected") from exc
    if (
        stat.S_ISLNK(before.st_mode)
        or _is_reparse(before)
        or not stat.S_ISREG(before.st_mode)
    ):
        raise ReproducibleCacheError(
            "published artifact must be a plain regular file"
        )
    if before.st_nlink != 1:
        if before.st_nlink == 2:
            raise _ConcurrentPublishHandoff
        raise ReproducibleCacheError(
            "published artifact cannot have hard-link aliases"
        )
    if before.st_size != len(content):
        raise ReproducibleCacheError(
            "existing reproducible artifact has different bytes"
        )
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if _file_snapshot(opened) != _file_snapshot(before):
            raise ReproducibleCacheError(
                "published artifact identity changed before it was opened"
            )
        observed = bytearray()
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, len(content) + 1 - len(observed)))
            if not chunk:
                break
            observed.extend(chunk)
            if len(observed) > len(content):
                break
        after_handle = os.fstat(descriptor)
    except OSError as exc:
        raise ReproducibleCacheError("published artifact cannot be read") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    try:
        after_path = path.lstat()
    except OSError as exc:
        raise ReproducibleCacheError(
            "published artifact disappeared during verification"
        ) from exc
    snapshots = {
        _file_snapshot(before),
        _file_snapshot(opened),
        _file_snapshot(after_handle),
        _file_snapshot(after_path),
    }
    if len(snapshots) != 1:
        raise ReproducibleCacheError(
            "published artifact changed during verification"
        )
    if expected_identity is not None and _file_identity(after_path) != expected_identity:
        raise ReproducibleCacheError(
            "published artifact differs from the fsynced temporary identity"
        )
    observed_bytes = bytes(observed)
    if (
        observed_bytes != content
        or sha256(observed_bytes).digest() != sha256(content).digest()
    ):
        raise ReproducibleCacheError(
            "existing reproducible artifact has different bytes"
        )


def _require_exact_file(
    path: Path,
    content: bytes,
    *,
    expected_identity: tuple[int, int, int] | None = None,
    allow_publish_handoff: bool,
) -> None:
    attempts = _HANDOFF_ATTEMPTS if allow_publish_handoff else 1
    for attempt in range(attempts):
        try:
            _read_exact_file_snapshot(
                path,
                content,
                expected_identity=expected_identity,
            )
            return
        except _ConcurrentPublishHandoff as exc:
            if attempt + 1 == attempts:
                raise ReproducibleCacheError(
                    "published artifact cannot have hard-link aliases"
                ) from exc
            time.sleep(_HANDOFF_SECONDS)
    raise AssertionError("unreachable exact-file verification branch")


def publish_reproducible_artifact(
    *,
    output_root: str | Path,
    relative_path: str,
    content: bytes,
) -> str:
    """Atomically publish one immutable file without replacing an existing path.

    The temporary file is flushed and fsynced in the destination directory.
    Publication uses an atomic hard-link create, whose existing-target branch
    succeeds only after exact byte comparison.  No call can replace an already
    published path, including a concurrent publisher's path.
    """

    if type(content) is not bytes:
        raise ReproducibleCacheError("reproducible artifact content must be bytes")
    root = _plain_output_root(output_root)
    parts = _logical_path_parts(relative_path)
    parent, directory_chain = _prepare_plain_parent(root, parts[:-1])
    target = parent / parts[-1]
    try:
        target.lstat()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise ReproducibleCacheError("artifact target cannot be inspected") from exc
    else:
        _require_exact_file(
            target,
            content,
            allow_publish_handoff=True,
        )
        return sha256(content).hexdigest()

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".reproducible-cache-",
        suffix=".tmp",
        dir=parent,
    )
    temporary = Path(temporary_name)
    temporary_pending = True
    primary_error: BaseException | None = None
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temporary_identity = _file_identity(os.fstat(handle.fileno()))
        _require_exact_file(
            temporary,
            content,
            expected_identity=temporary_identity,
            allow_publish_handoff=False,
        )
        _verify_directory_chain(directory_chain)
        try:
            os.link(temporary, target, follow_symlinks=False)
        except FileExistsError:
            _require_exact_file(
                target,
                content,
                allow_publish_handoff=True,
            )
        except OSError as exc:
            raise ReproducibleCacheError(
                "reproducible artifact cannot be atomically published"
            ) from exc
        else:
            try:
                temporary.unlink()
            except OSError as exc:
                raise ReproducibleCacheError(
                    "published artifact hard-link handoff cannot be completed"
                ) from exc
            temporary_pending = False
            _require_exact_file(
                target,
                content,
                expected_identity=temporary_identity,
                allow_publish_handoff=False,
            )
        _verify_directory_chain(directory_chain)
        return sha256(content).hexdigest()
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        if temporary_pending:
            try:
                temporary.unlink(missing_ok=True)
            except OSError as exc:
                if primary_error is None:
                    raise ReproducibleCacheError(
                        "reproducible artifact temporary file cannot be removed"
                    ) from exc


def publish_reproducible_cache(
    *,
    repository_root: str | Path,
    relative_path: str,
    content: bytes,
) -> str:
    """Publish one immutable artifact confined to ``local/cache``."""

    parts = _logical_path_parts(relative_path)
    if parts[:2] != ("local", "cache") or len(parts) < 3:
        raise ReproducibleCacheError(
            "reproducible cache path must be below local/cache"
        )
    return publish_reproducible_artifact(
        output_root=repository_root,
        relative_path=relative_path,
        content=content,
    )


__all__ = [
    "ReproducibleCacheError",
    "publish_reproducible_artifact",
    "publish_reproducible_cache",
    "reproducible_cache_implementation_sha256",
]
