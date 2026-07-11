"""Restricted canonical JSON for durable local identities."""

from __future__ import annotations

import json
from typing import TypeAlias, cast


CanonicalValue: TypeAlias = (
    dict[str, "CanonicalValue"]
    | list["CanonicalValue"]
    | str
    | int
    | bool
    | None
)


class CanonicalJSONError(ValueError):
    """Raised when a value or document violates the canonical JSON profile."""


def _validate(value: object, *, path: str, active: set[int]) -> None:
    if value is None or type(value) is bool or type(value) is int:
        return

    if type(value) is str:
        if not value.isascii():
            raise CanonicalJSONError(f"non-ASCII string at {path}")
        return

    if type(value) is list:
        marker = id(value)
        if marker in active:
            raise CanonicalJSONError(f"cyclic list at {path}")
        active.add(marker)
        try:
            for index, item in enumerate(value):
                _validate(item, path=f"{path}[{index}]", active=active)
        finally:
            active.remove(marker)
        return

    if type(value) is dict:
        marker = id(value)
        if marker in active:
            raise CanonicalJSONError(f"cyclic object at {path}")
        active.add(marker)
        try:
            for key, item in value.items():
                if type(key) is not str:
                    raise CanonicalJSONError(f"non-string object key at {path}")
                if not key.isascii():
                    raise CanonicalJSONError(f"non-ASCII object key at {path}")
                _validate(item, path=f"{path}.{key}", active=active)
        finally:
            active.remove(marker)
        return

    if type(value) is float:
        raise CanonicalJSONError(f"floating-point value at {path}")
    raise CanonicalJSONError(
        f"unsupported value type at {path}: {type(value).__name__}"
    )


def canonical_bytes(value: object) -> bytes:
    """Return the one canonical ASCII encoding for an allowed value."""

    _validate(value, path="$", active=set())
    text = json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        skipkeys=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return text.encode("ascii")


def canonical_text(value: object) -> str:
    """Return the canonical JSON encoding as ASCII text."""

    return canonical_bytes(value).decode("ascii")


def _reject_float(token: str) -> object:
    raise CanonicalJSONError(f"floating-point token is not allowed: {token}")


def _reject_constant(token: str) -> object:
    raise CanonicalJSONError(f"non-finite token is not allowed: {token}")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CanonicalJSONError(f"duplicate object key: {key}")
        result[key] = value
    return result


def parse_canonical(document: str | bytes) -> CanonicalValue:
    """Parse a document only if it already uses the canonical byte encoding."""

    if type(document) is bytes:
        try:
            raw = document.decode("ascii")
        except UnicodeDecodeError as exc:
            raise CanonicalJSONError("canonical JSON must be ASCII") from exc
        original = document
    elif type(document) is str:
        if not document.isascii():
            raise CanonicalJSONError("canonical JSON must be ASCII")
        raw = document
        original = document.encode("ascii")
    else:
        raise TypeError("document must be str or bytes")

    try:
        value = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
        )
    except CanonicalJSONError:
        raise
    except json.JSONDecodeError as exc:
        raise CanonicalJSONError(f"invalid JSON: {exc.msg}") from exc

    encoded = canonical_bytes(value)
    if encoded != original:
        raise CanonicalJSONError("document is valid JSON but not canonical")
    return cast(CanonicalValue, value)
