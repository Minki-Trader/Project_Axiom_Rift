"""Small transactional writer for repo state files.

The transaction is intentionally conservative: all drafts are validated and
written to sibling tmp files before any target is replaced.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class TransactionError(RuntimeError):
    """Raised when a state transaction cannot be prepared or committed."""


@dataclass(frozen=True)
class _Draft:
    path: Path
    text: str
    kind: str


def ensure_ascii_text(text: str, path: Path | None = None) -> None:
    try:
        text.encode("ascii")
    except UnicodeEncodeError as exc:
        target = f" for {path}" if path is not None else ""
        raise TransactionError(f"Non-ASCII state payload{target}") from exc


class StateTransaction:
    """Collect JSON/YAML/text drafts and replace targets after validation."""

    def __init__(self, root: Path | None = None, label: str = "state") -> None:
        self.root = root.resolve() if root is not None else None
        self.label = label
        self._drafts: dict[Path, _Draft] = {}
        self._validators: list[Callable[["StateTransaction"], None]] = []
        self._committed = False

    @property
    def draft_paths(self) -> tuple[Path, ...]:
        return tuple(self._drafts)

    def has_draft(self, path: Path) -> bool:
        return self._resolve(path) in self._drafts

    def add_validator(self, validator: Callable[["StateTransaction"], None]) -> None:
        self._validators.append(validator)

    def read_json(self, path: Path) -> Any:
        resolved = self._resolve(path)
        draft = self._drafts.get(resolved)
        if draft is not None:
            return json.loads(draft.text)
        return json.loads(resolved.read_text(encoding="ascii"))

    def read_yaml(self, path: Path) -> Any:
        resolved = self._resolve(path)
        draft = self._drafts.get(resolved)
        if draft is not None:
            return yaml.safe_load(draft.text)
        return yaml.safe_load(resolved.read_text(encoding="ascii"))

    def read_text(self, path: Path) -> str:
        resolved = self._resolve(path)
        draft = self._drafts.get(resolved)
        if draft is not None:
            return draft.text
        return resolved.read_text(encoding="ascii")

    def write_json(self, path: Path, payload: Any) -> None:
        try:
            text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
            json.loads(text)
        except (TypeError, ValueError) as exc:
            raise TransactionError(f"Invalid JSON draft for {path}: {exc}") from exc
        self._stage(path, text, "json")

    def write_yaml(self, path: Path, payload: Any, *, sort_keys: bool = False) -> None:
        try:
            text = yaml.safe_dump(payload, sort_keys=sort_keys, allow_unicode=False)
            yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise TransactionError(f"Invalid YAML draft for {path}: {exc}") from exc
        self._stage(path, text, "yaml")

    def write_text(self, path: Path, text: str, *, kind: str = "text") -> None:
        self._stage(path, text, kind)

    def sha256(self, path: Path) -> str:
        resolved = self._resolve(path)
        draft = self._drafts.get(resolved)
        if draft is not None:
            return hashlib.sha256(draft.text.encode("ascii")).hexdigest()
        digest = hashlib.sha256()
        with resolved.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def commit(self) -> None:
        if self._committed:
            raise TransactionError(f"Transaction already committed: {self.label}")
        for validator in self._validators:
            validator(self)
        tmp_pairs: list[tuple[Path, Path]] = []
        try:
            for index, draft in enumerate(self._drafts.values()):
                if not draft.path.parent.exists():
                    raise TransactionError(f"Missing target parent for {draft.path}")
                tmp = draft.path.with_name(f".tx{index}.tmp")
                tmp.write_text(draft.text, encoding="ascii", newline="\n")
                self._validate_tmp(tmp, draft.kind)
                tmp_pairs.append((tmp, draft.path))
            for tmp, target in tmp_pairs:
                self._replace_with_retry(tmp, target)
        except Exception as exc:
            if isinstance(exc, TransactionError):
                raise
            raise TransactionError(f"Commit failed for {self.label}: {exc}") from exc
        self._committed = True

    def _stage(self, path: Path, text: str, kind: str) -> None:
        resolved = self._resolve(path)
        ensure_ascii_text(text, resolved)
        if kind == "json":
            json.loads(text)
        elif kind == "yaml":
            yaml.safe_load(text)
        self._drafts[resolved] = _Draft(path=resolved, text=text, kind=kind)

    def _resolve(self, path: Path) -> Path:
        resolved = path.resolve()
        if self.root is not None:
            try:
                resolved.relative_to(self.root)
            except ValueError as exc:
                raise TransactionError(f"State path escapes root: {path}") from exc
        return resolved

    @staticmethod
    def _validate_tmp(path: Path, kind: str) -> None:
        text = path.read_text(encoding="ascii")
        ensure_ascii_text(text, path)
        if kind == "json":
            json.loads(text)
        elif kind == "yaml":
            yaml.safe_load(text)

    @staticmethod
    def _replace_with_retry(tmp: Path, target: Path) -> None:
        for attempt in range(5):
            try:
                os.replace(tmp, target)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.2 * (attempt + 1))
