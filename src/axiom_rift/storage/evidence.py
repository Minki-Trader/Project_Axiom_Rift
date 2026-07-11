"""Content-addressed local evidence storage."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import os
import tempfile


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


class EvidenceStore:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    def finalize(self, content: bytes) -> EvidenceArtifact:
        if type(content) is not bytes:
            raise TypeError("evidence content must be bytes")
        identity = sha256(content).hexdigest()
        relative = Path("sha256") / identity[:2] / identity
        target = self._root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if sha256(target.read_bytes()).hexdigest() != identity:
                raise RuntimeError("content-addressed evidence collision")
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
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()
        if sha256(target.read_bytes()).hexdigest() != identity:
            raise RuntimeError("evidence post-finalize hash mismatch")
        return EvidenceArtifact(identity, len(content), relative.as_posix())

    def verify(self, identity: str) -> EvidenceArtifact:
        """Verify one declared content hash without scanning the evidence store."""

        if (
            type(identity) is not str
            or len(identity) != 64
            or any(character not in "0123456789abcdef" for character in identity)
        ):
            raise ValueError("evidence identity must be a lowercase SHA-256 digest")
        relative = Path("sha256") / identity[:2] / identity
        target = self._root / relative
        if not target.is_file():
            raise FileNotFoundError(f"bound evidence is absent: {identity}")
        content = target.read_bytes()
        if sha256(content).hexdigest() != identity:
            raise RuntimeError(f"bound evidence hash mismatch: {identity}")
        return EvidenceArtifact(identity, len(content), relative.as_posix())

    def read_verified(self, identity: str) -> bytes:
        """Read one declared artifact after verifying its content identity."""

        if (
            type(identity) is not str
            or len(identity) != 64
            or any(character not in "0123456789abcdef" for character in identity)
        ):
            raise ValueError("evidence identity must be a lowercase SHA-256 digest")
        target = self._root / "sha256" / identity[:2] / identity
        if not target.is_file():
            raise FileNotFoundError(f"bound evidence is absent: {identity}")
        content = target.read_bytes()
        if sha256(content).hexdigest() != identity:
            raise RuntimeError(f"bound evidence hash mismatch: {identity}")
        return content

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
