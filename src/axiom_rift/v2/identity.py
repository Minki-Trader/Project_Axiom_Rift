"""Canonical identities and immutable V2 objects."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any


class IdentityError(RuntimeError):
    """Raised when an immutable identity cannot be trusted."""


def canonical_json_bytes(payload: Any) -> bytes:
    try:
        text = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise IdentityError(f"payload is not canonical JSON: {exc}") from exc
    return text.encode("ascii")


def sha256_payload(payload: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


class ObjectStore:
    """Write-once content-addressed object store."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, object_id: str) -> Path:
        if len(object_id) != 64 or any(char not in "0123456789abcdef" for char in object_id):
            raise IdentityError(f"invalid object id: {object_id}")
        return self.root / f"{object_id}.json"

    def put(self, kind: str, payload: Any) -> str:
        body = {"schema": "axiom_rift_v2_object_v1", "kind": kind, "payload": payload}
        object_id = sha256_payload(body)
        envelope = {**body, "object_id": object_id}
        data = canonical_json_bytes(envelope) + b"\n"
        target = self.path_for(object_id)
        if target.exists():
            self._verify(target, object_id)
            return object_id
        lock = target.with_suffix(".lock")
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise IdentityError(f"object lock exists: {lock}") from exc
        os.close(descriptor)
        temp = self.root / f".{object_id}.{uuid.uuid4().hex}.tmp"
        try:
            with temp.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            if target.exists():
                self._verify(target, object_id)
            else:
                os.replace(temp, target)
            self._verify(target, object_id)
        finally:
            temp.unlink(missing_ok=True)
            lock.unlink(missing_ok=True)
        return object_id

    def get(self, object_id: str) -> dict[str, Any]:
        path = self.path_for(object_id)
        if not path.is_file():
            raise IdentityError(f"object is missing: {object_id}")
        return self._verify(path, object_id)

    @staticmethod
    def _verify(path: Path, object_id: str) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="ascii"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise IdentityError(f"invalid object {path}: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("object_id") != object_id:
            raise IdentityError(f"object id mismatch: {path}")
        body = {key: value for key, value in payload.items() if key != "object_id"}
        if sha256_payload(body) != object_id:
            raise IdentityError(f"object content hash mismatch: {path}")
        return payload
