"""Read-only implementation-byte authority for production Job declarations."""

from __future__ import annotations

import ast
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
import re
from typing import Any

from axiom_rift.core.canonical import parse_canonical


class JobImplementationAuthorityError(RuntimeError):
    """Current implementation evidence is absent or internally inconsistent."""


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalImplementationSourceAuthority:
    """One Writer-authenticated historical reconstruction source."""

    path: str
    source_sha256: str
    original_study_id: str

    def __post_init__(self) -> None:
        if (
            type(self.path) is not str
            or not self.path
            or not self.path.isascii()
            or self.path.startswith("/")
            or ":" in self.path
            or "\\" in self.path
            or any(part in {"", ".", ".."} for part in self.path.split("/"))
        ):
            raise JobImplementationAuthorityError(
                "historical implementation source path is invalid"
            )
        _require_digest("historical implementation source", self.source_sha256)
        if (
            type(self.original_study_id) is not str
            or _CONTROL_ID_PATTERN.fullmatch(self.original_study_id) is None
            or not self.original_study_id.startswith("STU-")
        ):
            raise JobImplementationAuthorityError(
                "historical implementation source Study identity is invalid"
            )


_CONTROL_ID_PATTERN = re.compile(r"\b(?:MIS|STU)-[0-9]{4}\b")
_PRODUCTION_SUBJECT_KINDS = frozenset(
    {"Mission", "Initiative", "Study", "Executable", "Release"}
)
_HARDCODED_CONTROL_ID_CACHE_LIMIT = 4096
_HARDCODED_CONTROL_ID_CACHE: dict[str, tuple[str, ...]] = {}


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


def _passive_static_string(
    node: ast.AST,
    *,
    parents: Mapping[ast.AST, ast.AST],
) -> bool:
    """Return whether one static string is display or exception prose only."""

    current = node
    while current in parents:
        parent = parents[current]
        if isinstance(parent, ast.keyword) and parent.arg == "display_name":
            return True
        if isinstance(parent, ast.Call):
            call_parent = parents.get(parent)
            if (
                isinstance(call_parent, ast.Raise)
                and call_parent.exc is parent
                and parent.args
            ):
                first = parent.args[0]
                probe = node
                while probe in parents and probe is not first:
                    probe = parents[probe]
                if probe is first and isinstance(
                    first,
                    (ast.BinOp, ast.Constant, ast.JoinedStr),
                ):
                    return True
        current = parent
    return False


def _scan_hardcoded_control_ids(source: bytes) -> tuple[str, ...]:
    """Perform one uncached static control-identity scan."""

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
    parents = {
        child: owner
        for owner in ast.walk(tree)
        for child in ast.iter_child_nodes(owner)
    }
    for node in ast.walk(tree):
        if id(node) in docstrings or _passive_static_string(
            node,
            parents=parents,
        ):
            continue
        value = _static_string(node)
        if value is not None:
            found.update(_CONTROL_ID_PATTERN.findall(value))
    return tuple(sorted(found))


def hardcoded_control_ids(source: bytes) -> tuple[str, ...]:
    """Find static Mission/Study IDs once per content-addressed source.

    Job implementation artifacts are already authenticated by SHA-256 before
    this boundary.  Re-parsing the same immutable source closure at every
    Writer transition added no authority while repeatedly walking millions of
    AST nodes.  The bounded digest cache retains only the small derived result,
    not source bytes.
    """

    source_digest = sha256(source).hexdigest()
    cached = _HARDCODED_CONTROL_ID_CACHE.get(source_digest)
    if cached is not None:
        return cached
    result = _scan_hardcoded_control_ids(source)
    if len(_HARDCODED_CONTROL_ID_CACHE) >= _HARDCODED_CONTROL_ID_CACHE_LIMIT:
        oldest = next(iter(_HARDCODED_CONTROL_ID_CACHE))
        del _HARDCODED_CONTROL_ID_CACHE[oldest]
    _HARDCODED_CONTROL_ID_CACHE[source_digest] = result
    return result


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
    historical_source_authorities: tuple[
        HistoricalImplementationSourceAuthority, ...
    ] = (),
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
    if (
        type(historical_source_authorities) is not tuple
        or any(
            not isinstance(item, HistoricalImplementationSourceAuthority)
            for item in historical_source_authorities
        )
        or len(
            {item.source_sha256 for item in historical_source_authorities}
        )
        != len(historical_source_authorities)
    ):
        raise JobImplementationAuthorityError(
            "historical implementation source authority is invalid"
        )
    source_authority = {
        item.source_sha256: item for item in historical_source_authorities
    }
    artifact_bytes: dict[str, bytes] = {}
    closure_paths: dict[str, set[str]] = {}
    closure_artifacts: set[str] = set()
    for source_hash in implementation_manifest["artifact_hashes"]:
        try:
            _require_digest("implementation artifact", source_hash)
            source_bytes = artifact_reader(source_hash)
            artifact_bytes[source_hash] = source_bytes
            try:
                value = parse_canonical(source_bytes)
            except ValueError:
                value = None
            if (
                isinstance(value, Mapping)
                and value.get("schema")
                == "job_implementation_source_closure.v1"
            ):
                dependencies = value.get("dependencies")
                if not isinstance(dependencies, list):
                    raise JobImplementationAuthorityError(
                        "Job implementation source closure is invalid"
                    )
                closure_artifacts.add(source_hash)
                for dependency in dependencies:
                    if (
                        not isinstance(dependency, Mapping)
                        or set(dependency) != {"path", "sha256"}
                        or type(dependency.get("path")) is not str
                        or type(dependency.get("sha256")) is not str
                    ):
                        raise JobImplementationAuthorityError(
                            "Job implementation source closure is invalid"
                        )
                    path = dependency["path"]
                    digest = dependency["sha256"]
                    _require_digest("implementation closure source", digest)
                    if (
                        not path
                        or not path.isascii()
                        or path.startswith("/")
                        or ":" in path
                        or "\\" in path
                        or any(
                            part in {"", ".", ".."}
                            for part in path.split("/")
                        )
                    ):
                        raise JobImplementationAuthorityError(
                            "Job implementation source closure path is invalid"
                        )
                    closure_paths.setdefault(digest, set()).add(path)
        except JobImplementationAuthorityError:
            raise
        except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
            raise JobImplementationAuthorityError(
                "Job implementation artifact bytes are unavailable"
            ) from exc
    for source_hash, source_bytes in artifact_bytes.items():
        if source_hash in closure_artifacts:
            continue
        control_ids = hardcoded_control_ids(source_bytes)
        if control_ids:
            authority = source_authority.get(source_hash)
            if (
                authority is None
                or control_ids != (authority.original_study_id,)
                or closure_paths.get(source_hash) != {authority.path}
            ):
                raise JobImplementationAuthorityError(
                    "Job implementation hardcodes a Mission or Study identity "
                    "outside declared historical replay lineage; use a reusable "
                    "mechanism with declarative runtime binding"
                )
    return implementation_manifest


__all__ = [
    "JobImplementationAuthorityError",
    "HistoricalImplementationSourceAuthority",
    "hardcoded_control_ids",
    "implementation_source_closure_hashes",
    "require_job_implementation_evidence",
    "requires_current_source_authority",
]
