"""Content-addressed local evidence storage."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import os
import stat
import tempfile
from time import sleep

from axiom_rift.storage.path_boundary import (
    PathBoundaryError,
    ensure_link_free_directory_chain,
    require_link_free_directory_chain,
)


@dataclass(frozen=True, slots=True)
class EvidenceArtifact:
    sha256: str
    size_bytes: int
    relative_path: str

    def manifest(self) -> dict[str, str | int]:
        return {
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "relative_path": self.relative_path,
        }


@dataclass(frozen=True, slots=True)
class EvidenceManifestTrace:
    declared_path_count: int
    observed_path_count: int
    relative_paths: tuple[str, ...]
    directory_enumerations: int = 0


def _is_link_like(metadata: os.stat_result) -> bool:
    if stat.S_ISLNK(metadata.st_mode):
        return True
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(getattr(metadata, "st_file_attributes", 0) & reparse_flag)


def _require_link_free_directory_chain(path: Path) -> None:
    try:
        require_link_free_directory_chain(path)
    except PathBoundaryError as exc:
        raise RuntimeError(
            "content-addressed evidence directory chain is unavailable or link-like"
        ) from exc


def _ensure_link_free_directory_chain(path: Path) -> None:
    try:
        ensure_link_free_directory_chain(path)
    except PathBoundaryError as exc:
        raise RuntimeError(
            "content-addressed evidence directory chain is unavailable or link-like"
        ) from exc


def _file_identity(metadata: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def _single_link_regular_lstat(target: Path, identity: str) -> os.stat_result:
    for attempt in range(5):
        try:
            metadata = target.lstat()
        except FileNotFoundError:
            raise FileNotFoundError(f"bound evidence is absent: {identity}") from None
        except OSError as exc:
            raise RuntimeError(
                f"bound evidence path is unavailable: {identity}"
            ) from exc
        if _is_link_like(metadata) or not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError(f"bound evidence is link-like or non-regular: {identity}")
        if metadata.st_nlink == 1:
            return metadata
        if attempt < 4:
            # Atomic no-overwrite publication briefly has both the private
            # temporary name and the public content-addressed name linked to
            # the same flushed inode.  Do not confuse that bounded handoff
            # with a durable mutable hard-link alias.
            sleep(0.002)
    raise RuntimeError(f"bound evidence has a mutable hard-link alias: {identity}")


class EvidenceStore:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(os.path.abspath(root))

    def _target(self, identity: str) -> tuple[Path, Path]:
        relative = Path("sha256") / identity[:2] / identity
        return self._root / relative, relative

    def _read_verified_snapshot(self, identity: str) -> bytes:
        target, _relative = self._target(identity)
        _require_link_free_directory_chain(target.parent)
        path_before = _single_link_regular_lstat(target, identity)

        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(target, flags)
        except OSError as exc:
            raise RuntimeError(f"bound evidence cannot be opened safely: {identity}") from exc
        try:
            opened_before = os.fstat(descriptor)
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                content = handle.read()
            opened_after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        try:
            path_after = target.lstat()
        except OSError as exc:
            raise RuntimeError(
                f"bound evidence path changed during verification: {identity}"
            ) from exc
        if (
            _is_link_like(path_after)
            or not stat.S_ISREG(path_after.st_mode)
            or path_after.st_nlink != 1
            or _file_identity(path_before) != _file_identity(opened_before)
            or _file_identity(opened_before) != _file_identity(opened_after)
            or _file_identity(opened_after) != _file_identity(path_after)
        ):
            raise RuntimeError(
                f"bound evidence identity changed during verification: {identity}"
            )
        if sha256(content).hexdigest() != identity:
            raise RuntimeError(f"bound evidence hash mismatch: {identity}")
        return content

    def finalize(self, content: bytes) -> EvidenceArtifact:
        if type(content) is not bytes:
            raise TypeError("evidence content must be bytes")
        identity = sha256(content).hexdigest()
        target, relative = self._target(identity)
        _ensure_link_free_directory_chain(target.parent)
        try:
            self._read_verified_snapshot(identity)
        except FileNotFoundError:
            pass
        else:
            return EvidenceArtifact(identity, len(content), relative.as_posix())
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{identity}.", suffix=".tmp", dir=target.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                pass
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        self._read_verified_snapshot(identity)
        return EvidenceArtifact(identity, len(content), relative.as_posix())

    def verify(self, identity: str) -> EvidenceArtifact:
        """Verify one declared content hash without scanning the evidence store."""

        if (
            type(identity) is not str
            or len(identity) != 64
            or any(character not in "0123456789abcdef" for character in identity)
        ):
            raise ValueError("evidence identity must be a lowercase SHA-256 digest")
        _target, relative = self._target(identity)
        content = self._read_verified_snapshot(identity)
        return EvidenceArtifact(identity, len(content), relative.as_posix())

    def read_verified(self, identity: str) -> bytes:
        """Read one declared artifact after verifying its content identity."""

        if (
            type(identity) is not str
            or len(identity) != 64
            or any(character not in "0123456789abcdef" for character in identity)
        ):
            raise ValueError("evidence identity must be a lowercase SHA-256 digest")
        return self._read_verified_snapshot(identity)

    def verified_path(self, identity: str) -> Path:
        """Return a verified artifact path for a consumer that rechecks bytes.

        This capability is intentionally narrower than exposing the store root.
        Path-based consumers such as ``ValidationArtifact`` retain their own
        before/after hash checks around dispatch.
        """

        self.read_verified(identity)
        target, _relative = self._target(identity)
        return target

    def verify_manifest(
        self, identities: tuple[str, ...]
    ) -> tuple[tuple[EvidenceArtifact, ...], EvidenceManifestTrace]:
        """Verify only declared content-addressed paths and expose the path bound."""

        if type(identities) is not tuple:
            raise TypeError("evidence manifest identities must be a tuple")
        artifacts = tuple(self.verify(identity) for identity in identities)
        trace = EvidenceManifestTrace(
            declared_path_count=len(identities),
            observed_path_count=len(artifacts),
            relative_paths=tuple(artifact.relative_path for artifact in artifacts),
        )
        return artifacts, trace
