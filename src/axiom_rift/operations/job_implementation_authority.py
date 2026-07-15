"""Read-only implementation-byte authority for production Job declarations."""

from __future__ import annotations

import ast
from collections.abc import Callable, Mapping
import re
from typing import Any

from axiom_rift.core.canonical import parse_canonical


class JobImplementationAuthorityError(RuntimeError):
    """Current implementation evidence is absent or internally inconsistent."""


_CONTROL_ID_PATTERN = re.compile(r"\b(?:MIS|STU)-[0-9]{4}\b")
_PRODUCTION_SUBJECT_KINDS = frozenset(
    {"Mission", "Initiative", "Study", "Executable", "Release"}
)


def _static_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return node.value
        if isinstance(node.value, bytes):
            try:
                return node.value.decode("ascii")
            except UnicodeDecodeError:
                return None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_string(node.left)
        right = _static_string(node.right)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if not isinstance(value, ast.Constant) or not isinstance(
                value.value, str
            ):
                return None
            parts.append(value.value)
        return "".join(parts)
    return None


def hardcoded_control_ids(source: bytes) -> tuple[str, ...]:
    """Find static Mission/Study IDs in Python or conservatively in other code."""

    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError:
        return tuple(
            sorted(
                set(
                    _CONTROL_ID_PATTERN.findall(
                        source.decode("ascii", errors="ignore")
                    )
                )
            )
        )
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return tuple(sorted(set(_CONTROL_ID_PATTERN.findall(text))))
    docstrings: set[int] = set()
    for owner in ast.walk(tree):
        body = getattr(owner, "body", None)
        if (
            isinstance(body, list)
            and body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            docstrings.add(id(body[0].value))
    found: set[str] = set()
    for node in ast.walk(tree):
        if id(node) in docstrings:
            continue
        value = _static_string(node)
        if value is not None:
            found.update(_CONTROL_ID_PATTERN.findall(value))
    return tuple(sorted(found))


def implementation_source_closure_hashes(
    *,
    implementation_manifest: Mapping[str, Any],
    artifact_reader: Callable[[str], bytes],
) -> tuple[str, ...]:
    """Return typed source-closure artifacts without trusting their payload."""

    matches: list[str] = []
    for identity in implementation_manifest.get("artifact_hashes", []):
        try:
            value = parse_canonical(artifact_reader(identity))
        except ValueError:
            continue
        if (
            isinstance(value, Mapping)
            and value.get("schema")
            == "job_implementation_source_closure.v1"
        ):
            matches.append(identity)
    return tuple(sorted(matches))


def requires_current_source_authority(
    *,
    engineering_fixture: bool,
    evidence_subject_kind: object,
) -> bool:
    """Require current path-role authority for every production Job subject."""

    if type(engineering_fixture) is not bool:
        raise JobImplementationAuthorityError(
            "engineering fixture mode must be boolean"
        )
    if evidence_subject_kind not in _PRODUCTION_SUBJECT_KINDS:
        raise JobImplementationAuthorityError(
            "Job evidence subject kind is unsupported"
        )
    return not engineering_fixture


def _require_digest(name: str, value: object) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise JobImplementationAuthorityError(
            f"{name} must be a lowercase SHA-256 digest"
        )
    return value


def require_job_implementation_evidence(
    spec: Mapping[str, Any],
    *,
    artifact_reader: Callable[[str], bytes],
) -> Mapping[str, Any]:
    """Open one implementation manifest and every exact artifact byte."""

    identity = spec["implementation_identity"]
    try:
        implementation_manifest = parse_canonical(artifact_reader(identity))
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        raise JobImplementationAuthorityError(
            "Job implementation identity is not available canonical evidence"
        ) from exc
    if (
        not isinstance(implementation_manifest, dict)
        or set(implementation_manifest)
        != {"artifact_hashes", "callable_identity", "protocol", "schema"}
        or implementation_manifest.get("schema")
        != "job_implementation_evidence.v1"
        or implementation_manifest.get("callable_identity")
        != spec["callable_identity"]
        or type(implementation_manifest.get("protocol")) is not str
        or not implementation_manifest["protocol"]
        or not implementation_manifest["protocol"].isascii()
        or not isinstance(
            implementation_manifest.get("artifact_hashes"), list
        )
        or not implementation_manifest["artifact_hashes"]
        or any(
            type(source_hash) is not str
            for source_hash in implementation_manifest["artifact_hashes"]
        )
        or len(set(implementation_manifest["artifact_hashes"]))
        != len(implementation_manifest["artifact_hashes"])
        or implementation_manifest["artifact_hashes"]
        != sorted(implementation_manifest["artifact_hashes"])
    ):
        raise JobImplementationAuthorityError(
            "Job implementation evidence manifest is invalid"
        )
    for source_hash in implementation_manifest["artifact_hashes"]:
        try:
            _require_digest("implementation artifact", source_hash)
            source_bytes = artifact_reader(source_hash)
            if hardcoded_control_ids(source_bytes):
                raise JobImplementationAuthorityError(
                    "Job implementation hardcodes a Mission or Study identity "
                    "outside declared historical replay lineage; use a reusable "
                    "mechanism with declarative runtime binding"
                )
        except JobImplementationAuthorityError:
            raise
        except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
            raise JobImplementationAuthorityError(
                "Job implementation artifact bytes are unavailable"
            ) from exc
    return implementation_manifest


__all__ = [
    "JobImplementationAuthorityError",
    "hardcoded_control_ids",
    "implementation_source_closure_hashes",
    "require_job_implementation_evidence",
    "requires_current_source_authority",
]
