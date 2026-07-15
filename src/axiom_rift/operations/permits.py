"""Writer-issued, subject-specific typed capability tokens."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum, unique
from hashlib import sha256
from hmac import compare_digest, new as new_hmac
from pathlib import Path
from secrets import token_bytes
from typing import Any, Mapping
import os
import stat
import tempfile
from time import sleep

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
from axiom_rift.storage.path_boundary import (
    PathBoundaryError,
    ensure_link_free_directory_chain,
    require_link_free_directory_chain,
)


class PermitError(RuntimeError):
    """A capability is forged, stale, expired, revoked, or replayed."""


@unique
class PermitKind(StrEnum):
    SOURCE = "source"
    STUDY = "study"
    BATCH = "batch"
    JOB = "job"
    REPAIR = "repair"
    RUNTIME = "runtime"
    HOLDOUT = "holdout"
    RELEASE = "release"


@unique
class PermitStatus(StrEnum):
    ISSUED = "issued"
    CONSUMED = "consumed"
    REVOKED = "revoked"


@unique
class SubjectKind(StrEnum):
    MISSION = "Mission"
    INITIATIVE = "Initiative"
    STUDY = "Study"
    EXECUTABLE = "Executable"
    JOB = "Job"
    RELEASE = "Release"


def _ascii(name: str, value: str) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ValueError(f"{name} must be non-empty ASCII")
    return value


def _hash(name: str, value: str) -> str:
    _ascii(name, value)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _timestamp(name: str, value: str) -> datetime:
    _ascii(name, value)
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    if observed.tzinfo is None:
        raise ValueError(f"{name} must include a timezone")
    return observed.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True, kw_only=True)
class SubjectRef:
    kind: SubjectKind
    subject_id: str
    authorization_epoch: int
    authorization_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SubjectKind):
            raise TypeError("kind must be SubjectKind")
        _ascii("subject_id", self.subject_id)
        if isinstance(self.authorization_epoch, bool) or not isinstance(
            self.authorization_epoch, int
        ) or self.authorization_epoch < 1:
            raise ValueError("authorization_epoch must be a positive integer")
        _hash("authorization_hash", self.authorization_hash)

    @property
    def key(self) -> str:
        return f"{self.kind.value}:{self.subject_id}"

    def payload(self) -> dict[str, str | int]:
        return {
            "kind": self.kind.value,
            "subject_id": self.subject_id,
            "authorization_epoch": self.authorization_epoch,
            "authorization_hash": self.authorization_hash,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class Permit:
    permit_id: str
    kind: PermitKind
    subject: SubjectRef
    input_hash: str
    actions: tuple[str, ...]
    scope: tuple[str, ...]
    issued_at_utc: str
    expires_at_utc: str
    one_shot: bool
    audit_revision: int
    signature: str

    def __post_init__(self) -> None:
        _hash("permit_id", self.permit_id)
        if not isinstance(self.kind, PermitKind):
            raise TypeError("kind must be PermitKind")
        if not isinstance(self.subject, SubjectRef):
            raise TypeError("subject must be SubjectRef")
        _hash("input_hash", self.input_hash)
        for name, values in (("actions", self.actions), ("scope", self.scope)):
            if type(values) is not tuple or not values:
                raise ValueError(f"{name} must be a non-empty tuple")
            if len(set(values)) != len(values):
                raise ValueError(f"{name} must not contain duplicates")
            for index, value in enumerate(values):
                _ascii(f"{name}[{index}]", value)
            if values != tuple(sorted(values)):
                raise ValueError(f"{name} must be sorted")
        issued = _timestamp("issued_at_utc", self.issued_at_utc)
        expires = _timestamp("expires_at_utc", self.expires_at_utc)
        if expires <= issued:
            raise ValueError("permit expiration must follow issue time")
        if type(self.one_shot) is not bool:
            raise TypeError("one_shot must be bool")
        if isinstance(self.audit_revision, bool) or not isinstance(
            self.audit_revision, int
        ) or self.audit_revision < 0:
            raise ValueError("audit_revision must be a non-negative integer")
        _hash("signature", self.signature)

    def unsigned_payload(self) -> dict[str, Any]:
        return {
            "schema": "typed_permit",
            "kind": self.kind.value,
            "subject": self.subject.payload(),
            "input_hash": self.input_hash,
            "actions": list(self.actions),
            "scope": list(self.scope),
            "issued_at_utc": self.issued_at_utc,
            "expires_at_utc": self.expires_at_utc,
            "one_shot": self.one_shot,
            "audit_revision": self.audit_revision,
        }

    def payload(self) -> dict[str, Any]:
        return {
            **self.unsigned_payload(),
            "permit_id": self.permit_id,
            "signature": self.signature,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Permit":
        subject = value["subject"]
        return cls(
            permit_id=value["permit_id"],
            kind=PermitKind(value["kind"]),
            subject=SubjectRef(
                kind=SubjectKind(subject["kind"]),
                subject_id=subject["subject_id"],
                authorization_epoch=subject["authorization_epoch"],
                authorization_hash=subject["authorization_hash"],
            ),
            input_hash=value["input_hash"],
            actions=tuple(value["actions"]),
            scope=tuple(value["scope"]),
            issued_at_utc=value["issued_at_utc"],
            expires_at_utc=value["expires_at_utc"],
            one_shot=value["one_shot"],
            audit_revision=value["audit_revision"],
            signature=value["signature"],
        )


class PermitAuthority:
    def __init__(self, secret: bytes) -> None:
        if type(secret) is not bytes or len(secret) < 32:
            raise ValueError("permit secret must contain at least 32 bytes")
        self._secret = secret

    def _signature(self, unsigned: Mapping[str, Any]) -> str:
        return new_hmac(self._secret, canonical_bytes(dict(unsigned)), sha256).hexdigest()

    def issue(
        self,
        *,
        kind: PermitKind,
        subject: SubjectRef,
        input_hash: str,
        actions: tuple[str, ...],
        scope: tuple[str, ...],
        issued_at_utc: str,
        expires_at_utc: str,
        one_shot: bool,
        audit_revision: int,
    ) -> Permit:
        normalized_actions = tuple(sorted(actions))
        normalized_scope = tuple(sorted(scope))
        unsigned = {
            "schema": "typed_permit",
            "kind": kind.value,
            "subject": subject.payload(),
            "input_hash": _hash("input_hash", input_hash),
            "actions": list(normalized_actions),
            "scope": list(normalized_scope),
            "issued_at_utc": issued_at_utc,
            "expires_at_utc": expires_at_utc,
            "one_shot": one_shot,
            "audit_revision": audit_revision,
        }
        permit_id = canonical_digest(domain="permit", payload=unsigned)
        return Permit(
            permit_id=permit_id,
            kind=kind,
            subject=subject,
            input_hash=input_hash,
            actions=normalized_actions,
            scope=normalized_scope,
            issued_at_utc=issued_at_utc,
            expires_at_utc=expires_at_utc,
            one_shot=one_shot,
            audit_revision=audit_revision,
            signature=self._signature(unsigned),
        )

    def validate(
        self,
        permit: Permit,
        *,
        expected_kind: PermitKind,
        action: str,
        current_subject: SubjectRef,
        status: PermitStatus,
        now_utc: str,
        required_scope: tuple[str, ...] = (),
        expected_input_hash: str | None = None,
    ) -> None:
        expected_id = canonical_digest(
            domain="permit", payload=permit.unsigned_payload()
        )
        expected_signature = self._signature(permit.unsigned_payload())
        if not compare_digest(permit.permit_id, expected_id) or not compare_digest(
            permit.signature, expected_signature
        ):
            raise PermitError("forged permit")
        if permit.kind is not expected_kind:
            raise PermitError("wrong permit kind")
        if permit.subject != current_subject:
            raise PermitError("stale or wrong permit subject authorization")
        if status is PermitStatus.REVOKED:
            raise PermitError("revoked permit")
        if status is PermitStatus.CONSUMED:
            raise PermitError("replayed permit")
        if status is not PermitStatus.ISSUED:
            raise PermitError("unknown permit status")
        if action not in permit.actions:
            raise PermitError("permit action is outside capability")
        if not set(required_scope).issubset(permit.scope):
            raise PermitError("permit scope is insufficient")
        if expected_input_hash is not None and permit.input_hash != expected_input_hash:
            raise PermitError("permit input identity mismatch")
        observed_now = _timestamp("now_utc", now_utc)
        if observed_now < _timestamp("issued_at_utc", permit.issued_at_utc):
            raise PermitError("permit is not yet valid")
        if observed_now >= _timestamp("expires_at_utc", permit.expires_at_utc):
            raise PermitError("expired permit")


def _key_link_like(metadata: os.stat_result) -> bool:
    if stat.S_ISLNK(metadata.st_mode):
        return True
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(getattr(metadata, "st_file_attributes", 0) & reparse_flag)


def _key_file_identity(
    metadata: os.stat_result,
) -> tuple[int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def _require_key_directory_chain(path: Path) -> None:
    try:
        require_link_free_directory_chain(path)
    except PathBoundaryError as exc:
        raise PermitError(
            "local permit key directory chain is unavailable or link-like"
        ) from exc


def _ensure_key_directory_chain(path: Path) -> None:
    try:
        ensure_link_free_directory_chain(path)
    except PathBoundaryError as exc:
        raise PermitError(
            "local permit key directory chain is unavailable or link-like"
        ) from exc


def _key_lstat(path: Path) -> os.stat_result:
    for attempt in range(5):
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise PermitError("local permit key path is unavailable") from exc
        if _key_link_like(metadata) or not stat.S_ISREG(metadata.st_mode):
            raise PermitError("local permit key is link-like or non-regular")
        if metadata.st_nlink == 1:
            return metadata
        if attempt < 4:
            sleep(0.002)
    raise PermitError("local permit key has a mutable hard-link alias")


def _read_key_snapshot(path: Path) -> bytes:
    _require_key_directory_chain(path.parent)
    before = _key_lstat(path)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise PermitError("local permit key cannot be opened safely") from exc
    try:
        opened_before = os.fstat(descriptor)
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            secret = handle.read(33)
        opened_after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    try:
        after = path.lstat()
    except OSError as exc:
        raise PermitError("local permit key changed during read") from exc
    if (
        _key_link_like(after)
        or not stat.S_ISREG(after.st_mode)
        or after.st_nlink != 1
        or _key_file_identity(before) != _key_file_identity(opened_before)
        or _key_file_identity(opened_before) != _key_file_identity(opened_after)
        or _key_file_identity(opened_after) != _key_file_identity(after)
    ):
        raise PermitError("local permit key identity changed during read")
    if len(secret) != 32:
        raise PermitError("local permit key is invalid")
    return secret


class PermitKeyStore:
    """Create the local permit key only when a future Mission needs it."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(os.path.abspath(path))

    def load_or_create(self) -> bytes:
        _ensure_key_directory_chain(self.path.parent)
        try:
            return _read_key_snapshot(self.path)
        except FileNotFoundError:
            pass
        secret = token_bytes(32)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".permit-key.", suffix=".tmp", dir=self.path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(secret)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, self.path)
            except FileExistsError:
                pass
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        # mkstemp creates the private file with owner-only permissions before
        # publication.  Never chmod the public path: a concurrent path swap
        # could otherwise redirect that metadata operation through a link.
        observed = _read_key_snapshot(self.path)
        if observed != secret:
            # Another concurrent creator won.  Returning its durable key is the
            # only valid result; returning this process's discarded random key
            # would create immediately unverifiable permits.
            return observed
        return secret
