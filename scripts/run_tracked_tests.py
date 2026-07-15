#!/usr/bin/env python3
"""Run pytest from an exact Git-tracked test manifest."""

from __future__ import annotations

import argparse
from functools import lru_cache
from hashlib import sha256
from importlib import metadata
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import sysconfig
import time
from tempfile import TemporaryDirectory
from typing import Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from axiom_rift.core.canonical import (  # noqa: E402
    CanonicalJSONError,
    canonical_bytes,
    parse_canonical,
)
from axiom_rift.storage.atomic_file import (  # noqa: E402
    AtomicFileError,
    publish_stable_regular_file_if_changed,
    replace_stable_regular_file,
)
from axiom_rift.storage.journal import (  # noqa: E402
    JournalIntegrityError,
    read_journal_snapshot,
)
from axiom_rift.storage.path_boundary import (  # noqa: E402
    PathBoundaryError,
    ensure_link_free_directory_chain,
    require_link_free_directory_chain,
)


_LOCAL_SUBPROCESS_TIMEOUT_SECONDS = 2 * 60


def _git(root: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ("git", *arguments),
        cwd=root,
        env=_git_environment(),
        check=True,
        capture_output=True,
        timeout=_LOCAL_SUBPROCESS_TIMEOUT_SECONDS,
    ).stdout


def _isolated_git(root: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ("git", *arguments),
        cwd=root,
        env=_isolated_git_environment(),
        check=True,
        capture_output=True,
        timeout=_LOCAL_SUBPROCESS_TIMEOUT_SECONDS,
    ).stdout


_SAFE_PYTEST_FLAGS = frozenset(
    {
        "-q",
        "--quiet",
        "-v",
        "--verbose",
        "-x",
        "--exitfirst",
        "-s",
        "--capture=no",
        "--disable-warnings",
        "--strict-config",
        "--strict-markers",
        "--showlocals",
        "-l",
        "--no-header",
        "--no-summary",
    }
)
_SAFE_PYTEST_PREFIXES = (
    "--durations=",
    "--durations-min=",
    "--maxfail=",
    "--tb=",
)
_HOST_ENVIRONMENT_ALLOWLIST = frozenset(
    {
        "COMSPEC",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "NUMBER_OF_PROCESSORS",
        "OS",
        "PATHEXT",
        "PROCESSOR_ARCHITECTURE",
        "PROCESSOR_IDENTIFIER",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TERM",
        "WINDIR",
    }
)
_PROJECTION_REBUILD_REQUIREMENTS = frozenset(
    {
        "OPERATING_DIRECTION.md",
        "src/axiom_rift/cli.py",
        "src/axiom_rift/operations/writer.py",
        "state/control.json",
    }
)
_FOUNDATION_DATA_PATH = "foundation/data.yaml"
_TEST_EVIDENCE_MANIFEST_PATH = "tests/evidence_inputs.txt"
_TEST_EVIDENCE_ROLE = "test_evidence"
_TEST_EVIDENCE_PREFIX = PurePosixPath("local/evidence/sha256")
_MAX_TEST_EVIDENCE_INPUTS = 512
# Historical evaluation traces are bounded below the aggregate allowance but
# can legitimately exceed 8 MiB.  Keep a finite per-object ceiling without
# excluding the exact 11.8 MiB STU-0106 traces required by reconstruction tests.
_MAX_TEST_EVIDENCE_FILE_BYTES = 16 * 1024 * 1024
_MAX_TEST_EVIDENCE_TOTAL_BYTES = 64 * 1024 * 1024
_PROTECTED_INPUT_RULES = (
    ("observed_development", PurePosixPath("data/processed/datasets")),
    ("split_artifact", PurePosixPath("data/processed/coverage_audits")),
)
_MATERIALIZED_INPUT_RULES = (
    *_PROTECTED_INPUT_RULES,
    (_TEST_EVIDENCE_ROLE, _TEST_EVIDENCE_PREFIX),
)
_OBSERVED_DEVELOPMENT_FIELDS = frozenset(
    {
        "path",
        "sha256",
        "byte_count",
        "row_count",
        "first_time",
        "last_time",
        "parent_dataset_sha256",
        "split_artifact_sha256",
        "derivation",
    }
)
_OBSERVED_DEVELOPMENT_DERIVATION = "exact_prefix_before_quarantined_tail"
_DEFAULT_FOCUSED_PYTEST_TIMEOUT_SECONDS = 30 * 60
_DEFAULT_FULL_PYTEST_TIMEOUT_SECONDS = 2 * 60 * 60
_MAX_PYTEST_TIMEOUT_SECONDS = 24 * 60 * 60
_HEAD_AUTHORITY_TRANSITION_MODE = "explicit_head_authority_transition_recovery"
_HEAD_AUTHORITY_TRANSITION_AUTHORITY = (
    "git_head_declared_authority_with_identical_index_control_journal"
)


def _paths(content: bytes) -> tuple[str, ...]:
    values = tuple(
        item.decode("utf-8") for item in content.split(b"\0") if item
    )
    for value in values:
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
            or path.as_posix() != value
        ):
            raise RuntimeError("Git returned an invalid test path")
    return values


def _is_pytest_file(path: str) -> bool:
    value = PurePosixPath(path)
    return value.suffix == ".py" and value.name.startswith("test_")


def _validate_pytest_args(values: Sequence[str]) -> tuple[str, ...]:
    """Accept presentation and fail-fast controls, never collection authority."""

    result: list[str] = []
    for value in values:
        if type(value) is not str or not value:
            raise RuntimeError("pytest argument is invalid")
        if value in _SAFE_PYTEST_FLAGS or any(
            value.startswith(prefix) and value != prefix
            for prefix in _SAFE_PYTEST_PREFIXES
        ):
            result.append(value)
            continue
        raise RuntimeError(
            "pytest argument may alter the index-bound collection or plugin "
            f"environment: {value}"
        )
    return tuple(result)


def _validate_execution_timeout(value: object) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > _MAX_PYTEST_TIMEOUT_SECONDS
    ):
        raise RuntimeError(
            "tracked pytest timeout must be an integer from 1 through "
            f"{_MAX_PYTEST_TIMEOUT_SECONDS} seconds"
        )
    return value


def _validate_test_selection(
    values: Sequence[str],
    *,
    tracked: Sequence[str],
) -> tuple[str, ...]:
    """Accept only exact frozen test files or identifier-only node prefixes."""

    tracked_set = set(tracked)
    selected: list[str] = []
    for value in values:
        if type(value) is not str or not value or not value.isascii():
            raise RuntimeError("tracked test selector is invalid")
        path, *nodes = value.split("::")
        if path not in tracked_set:
            raise RuntimeError(
                "tracked test selector is not an exact frozen test path: "
                + path
            )
        if nodes and (
            any(not node or not node.isidentifier() for node in nodes)
            or not (
                nodes[-1].startswith("test_")
                or nodes[-1].startswith("Test")
            )
        ):
            raise RuntimeError(
                "tracked test selector node prefix is not exact: " + value
            )
        selected.append(value)
    ordered = tuple(sorted(selected))
    if len(ordered) != len(set(ordered)):
        raise RuntimeError("tracked test selectors are not unique")
    for index, selector in enumerate(ordered):
        if any(
            candidate.startswith(selector + "::")
            for candidate in ordered[index + 1 :]
        ):
            raise RuntimeError("tracked test selectors overlap")
    return ordered


def _tree_blob(root: Path, index_tree: str, path: str) -> bytes:
    try:
        return _git(root, "show", f"{index_tree}:{path}")
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"frozen index-tree blob is unavailable: {path}"
        ) from exc


def _tree_blob_id(root: Path, index_tree: str, path: str) -> str:
    try:
        return (
            _git(root, "rev-parse", f"{index_tree}:{path}")
            .decode("ascii")
            .strip()
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"frozen index-tree blob identity is unavailable: {path}"
        ) from exc


def _tree_regular_entry(root: Path, tree: str, path: str) -> tuple[str, str]:
    rows = tuple(
        row
        for row in _git(root, "ls-tree", "-z", tree, "--", path).split(b"\0")
        if row
    )
    if len(rows) != 1:
        raise RuntimeError(f"frozen authority path is unavailable: {path}")
    header, separator, raw_path = rows[0].partition(b"\t")
    fields = header.split()
    decoded = _paths(raw_path + b"\0")
    if (
        not separator
        or len(fields) != 3
        or fields[0] not in {b"100644", b"100755"}
        or fields[1] != b"blob"
        or decoded != (path,)
    ):
        raise RuntimeError(f"frozen authority path is not regular: {path}")
    return fields[0].decode("ascii"), fields[2].decode("ascii")


def _control_authority_paths(content: bytes) -> tuple[str, ...]:
    try:
        control = parse_canonical(content)
    except CanonicalJSONError as exc:
        raise RuntimeError("indexed control authority is not canonical") from exc
    authority = control.get("authority") if isinstance(control, dict) else None
    if (
        not isinstance(authority, dict)
        or set(authority)
        != {
            "contracts",
            "foundation_inputs",
            "graph_count",
            "manifest_digest",
            "operating_direction",
        }
        or authority.get("graph_count") != 1
        or not isinstance(authority.get("contracts"), list)
        or not authority["contracts"]
        or not isinstance(authority.get("foundation_inputs"), list)
        or not authority["foundation_inputs"]
    ):
        raise RuntimeError("indexed control authority surface is invalid")
    values = (
        authority.get("operating_direction"),
        *authority["contracts"],
        *authority["foundation_inputs"],
    )
    paths: list[str] = []
    for value in values:
        if type(value) is not str or not value or not value.isascii():
            raise RuntimeError("indexed control authority path is invalid")
        relative = PurePosixPath(value)
        if (
            relative.is_absolute()
            or relative.as_posix() != value
            or any(part in {"", ".", ".."} for part in relative.parts)
            or "\\" in value
            or ":" in value
        ):
            raise RuntimeError("indexed control authority path escapes its tree")
        paths.append(value)
    if len(paths) != len(set(paths)):
        raise RuntimeError("indexed control authority paths are not unique")
    return tuple(paths)


def _tree_journal_paths(
    root: Path, *, tree: str, tracked_paths: set[str]
) -> tuple[str, ...]:
    def load(path: str) -> bytes | None:
        return _tree_blob(root, tree, path) if path in tracked_paths else None

    try:
        snapshot = read_journal_snapshot(
            load,
            listed_paths=tracked_paths,
            validate_events=False,
        )
    except JournalIntegrityError as exc:
        raise RuntimeError("frozen Journal authority is invalid") from exc
    if snapshot.layout == "empty" or snapshot.active_path is None:
        raise RuntimeError("frozen Journal authority is unavailable")
    return tuple(
        sorted(
            {
                *(() if snapshot.manifest_path is None else (snapshot.manifest_path,)),
                *snapshot.segment_paths,
                *snapshot.seal_paths,
                snapshot.active_path,
            }
        )
    )


def _head_authority_transition_plan(
    root: Path,
    *,
    head: str,
    index_tree: str,
    index_paths: set[str],
) -> dict[str, object]:
    head_tree = _git(root, "rev-parse", f"{head}^{{tree}}").decode("ascii").strip()
    head_paths = set(_tree_paths(root, head_tree))
    control_path = "state/control.json"
    head_control = _tree_regular_entry(root, head_tree, control_path)
    index_control = _tree_regular_entry(root, index_tree, control_path)
    if head_control != index_control:
        raise RuntimeError(
            "HEAD and index control differ at authority transition"
        )
    head_journal = _tree_journal_paths(
        root, tree=head_tree, tracked_paths=head_paths
    )
    index_journal = _tree_journal_paths(
        root, tree=index_tree, tracked_paths=index_paths
    )
    if head_journal != index_journal:
        raise RuntimeError("HEAD and index Journal layouts differ")
    stable = [{"blob": index_control[1], "path": control_path}]
    for path in index_journal:
        head_entry = _tree_regular_entry(root, head_tree, path)
        index_entry = _tree_regular_entry(root, index_tree, path)
        if head_entry != index_entry:
            raise RuntimeError(f"HEAD and index Journal authority differ: {path}")
        stable.append({"blob": index_entry[1], "path": path})
    declared = _control_authority_paths(_tree_blob(root, index_tree, control_path))
    if set(declared).intersection(item["path"] for item in stable):
        raise RuntimeError("declared authority overlaps control or Journal")
    changed: list[dict[str, str]] = []
    for path in declared:
        head_mode, head_blob = _tree_regular_entry(root, head_tree, path)
        index_mode, index_blob = _tree_regular_entry(root, index_tree, path)
        if head_mode != "100644" or index_mode != "100644":
            raise RuntimeError(f"declared authority is not regular text: {path}")
        if head_blob != index_blob:
            changed.append(
                {
                    "head_blob": head_blob,
                    "head_sha256": sha256(_tree_blob(root, head_tree, path)).hexdigest(),
                    "index_blob": index_blob,
                    "index_sha256": sha256(_tree_blob(root, index_tree, path)).hexdigest(),
                    "path": path,
                }
            )
    if not changed:
        raise RuntimeError("HEAD authority transition has no declared path drift")
    return {
        "authority": _HEAD_AUTHORITY_TRANSITION_AUTHORITY,
        "control_declared_authority_paths": list(declared),
        "control_journal_authority": sorted(stable, key=lambda item: item["path"]),
        "historical_git_head_tree": head_tree,
        "mode": _HEAD_AUTHORITY_TRANSITION_MODE,
        "prospective_git_index_tree": index_tree,
        "temporary_authority_paths": sorted(changed, key=lambda item: item["path"]),
    }


def _tree_test_blob_ids(
    root: Path,
    index_tree: str,
    paths: Sequence[str],
) -> tuple[str, ...]:
    """Resolve test blob identities with one tree read, not one Git process each."""

    requested = tuple(paths)
    if len(requested) != len(set(requested)):
        raise RuntimeError("tracked test paths are not unique")
    entries: dict[str, str] = {}
    for row in _git(
        root,
        "ls-tree",
        "-r",
        "-z",
        index_tree,
        "--",
        "tests",
    ).split(b"\0"):
        if not row:
            continue
        header, separator, raw_path = row.partition(b"\t")
        fields = header.split()
        decoded = _paths(raw_path + b"\0")
        if (
            not separator
            or len(fields) != 3
            or fields[0] not in {b"100644", b"100755"}
            or fields[1] != b"blob"
            or len(decoded) != 1
        ):
            raise RuntimeError("frozen test tree contains a malformed entry")
        path = decoded[0]
        blob = fields[2].decode("ascii")
        if path in entries or not blob or any(
            character not in "0123456789abcdef" for character in blob
        ):
            raise RuntimeError("frozen test tree blob identity is malformed")
        entries[path] = blob
    missing = sorted(set(requested).difference(entries))
    if missing:
        raise RuntimeError(
            "frozen test tree blobs are unavailable: " + ", ".join(missing)
        )
    return tuple(entries[path] for path in requested)


def _batch_blob_contents(
    root: Path,
    blob_ids: Sequence[str],
) -> tuple[bytes, ...]:
    """Read exact index blobs through one size-framed ``cat-file`` process."""

    requested = tuple(blob_ids)
    completed = subprocess.run(
        ("git", "cat-file", "--batch"),
        cwd=root,
        check=True,
        capture_output=True,
        input=b"".join(blob.encode("ascii") + b"\n" for blob in requested),
        timeout=_LOCAL_SUBPROCESS_TIMEOUT_SECONDS,
    )
    output = completed.stdout
    offset = 0
    contents: list[bytes] = []
    for expected in requested:
        line_end = output.find(b"\n", offset)
        if line_end < 0:
            raise RuntimeError("Git batch blob response is truncated")
        header = output[offset:line_end].split()
        if len(header) != 3 or header[0].decode("ascii") != expected:
            raise RuntimeError("Git batch blob response identity differs")
        if header[1] != b"blob":
            raise RuntimeError("Git batch object is not a blob")
        try:
            size = int(header[2])
        except ValueError as exc:
            raise RuntimeError("Git batch blob size is malformed") from exc
        start = line_end + 1
        end = start + size
        if size < 0 or end >= len(output) or output[end : end + 1] != b"\n":
            raise RuntimeError("Git batch blob content is truncated")
        contents.append(output[start:end])
        offset = end + 1
    if offset != len(output):
        raise RuntimeError("Git batch blob response has trailing bytes")
    return tuple(contents)


def _worktree_blob_ids(root: Path, paths: Sequence[str]) -> tuple[str, ...]:
    """Hash worktree tests in bounded batches while honoring Git attributes."""

    requested = tuple(paths)
    result: list[str] = []
    for offset in range(0, len(requested), 64):
        batch = requested[offset : offset + 64]
        rows = _git(root, "hash-object", "--", *batch).splitlines()
        if len(rows) != len(batch):
            raise RuntimeError("Git worktree blob response is incomplete")
        for row in rows:
            try:
                blob = row.decode("ascii")
            except UnicodeDecodeError as exc:
                raise RuntimeError("Git worktree blob identity is malformed") from exc
            if not blob or any(
                character not in "0123456789abcdef" for character in blob
            ):
                raise RuntimeError("Git worktree blob identity is malformed")
            result.append(blob)
    return tuple(result)


def _tree_paths(root: Path, index_tree: str) -> tuple[str, ...]:
    return _paths(
        _git(root, "ls-tree", "-r", "-z", "--name-only", index_tree)
    )


def _regular_tree_modes(root: Path, index_tree: str) -> dict[str, str]:
    """Read the exact regular-file modes before detaching Git metadata."""

    result: dict[str, str] = {}
    for row in _git(root, "ls-tree", "-r", "-z", index_tree).split(b"\0"):
        if not row:
            continue
        header, separator, raw_path = row.partition(b"\t")
        fields = header.split()
        if (
            not separator
            or len(fields) != 3
            or fields[1] != b"blob"
            or fields[0] not in {b"100644", b"100755"}
        ):
            raise RuntimeError(
                "frozen index tree contains a non-regular file entry"
            )
        paths = _paths(raw_path + b"\0")
        if len(paths) != 1 or paths[0] in result:
            raise RuntimeError("frozen index tree mode path is ambiguous")
        result[paths[0]] = fields[0].decode("ascii")
    if not result:
        raise RuntimeError("frozen index tree has no regular file entries")
    return result


def _is_link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction is not None and is_junction())


def _protected_relative_path(role: str, value: object) -> PurePosixPath:
    if type(value) is not str or not value:
        raise RuntimeError(f"Foundation protected input path is invalid: {role}")
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise RuntimeError(
            f"Foundation protected input path is not ASCII: {role}"
        ) from exc
    relative = PurePosixPath(value)
    prefix = dict(_MATERIALIZED_INPUT_RULES).get(role)
    if (
        prefix is None
        or any(
            character
            not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_./-"
            for character in value
        )
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.as_posix() != value
        or relative.parts[: len(prefix.parts)] != prefix.parts
        or len(relative.parts) <= len(prefix.parts)
    ):
        raise RuntimeError(
            f"Foundation protected input is not confined to its approved data lane: {role}"
        )
    return relative


def _protected_repository_file(root: Path, role: str, value: object) -> Path:
    relative = _protected_relative_path(role, value)
    candidate = root.joinpath(*relative.parts)
    cursor = candidate
    while cursor != root:
        if _is_link_like(cursor):
            raise RuntimeError(
                f"Foundation protected input traverses a link-like path: {role}"
            )
        cursor = cursor.parent
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError(
            f"Foundation protected input is unavailable: {role}"
        ) from exc
    if resolved != candidate or not candidate.is_file():
        raise RuntimeError(
            f"Foundation protected input is not a confined regular file: {role}"
        )
    return candidate


def _hash_file(path: Path) -> tuple[str, int]:
    digest = sha256()
    size = 0
    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            visible_before = path.lstat()
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or (before.st_dev, before.st_ino)
                != (visible_before.st_dev, visible_before.st_ino)
            ):
                raise RuntimeError(
                    f"protected input is not one exact regular file: {path.name}"
                )
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
            after = os.fstat(handle.fileno())
            visible_after = path.lstat()
    except OSError as exc:
        raise RuntimeError(f"cannot hash protected input: {path.name}") from exc
    identity = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_nlink,
    )
    if identity != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_nlink,
    ) or identity != (
        visible_after.st_dev,
        visible_after.st_ino,
        visible_after.st_size,
        visible_after.st_mtime_ns,
        visible_after.st_nlink,
    ):
        raise RuntimeError(f"protected input changed while hashing: {path.name}")
    return digest.hexdigest(), size


def _protected_foundation_fields(text: str) -> dict[str, object]:
    """Read the small protected-input subset without a startup dependency."""

    if "\t" in text:
        raise RuntimeError("tracked Foundation data manifest contains tabs")
    schema: str | None = None
    current_section: str | None = None
    seen_top_level: set[str] = set()
    roles: dict[str, dict[str, str]] = {
        role: {} for role, _ in _PROTECTED_INPUT_RULES
    }
    for raw_line in text.splitlines():
        if not raw_line or raw_line.lstrip().startswith("#"):
            continue
        if not raw_line.startswith(" "):
            key, separator, raw_value = raw_line.partition(":")
            if not separator or not key or any(
                character not in "abcdefghijklmnopqrstuvwxyz0123456789_"
                for character in key
            ):
                raise RuntimeError("tracked Foundation data manifest is malformed")
            if key in seen_top_level:
                raise RuntimeError(
                    "tracked Foundation data manifest has duplicate top-level keys"
                )
            seen_top_level.add(key)
            value = _foundation_scalar(raw_value)
            current_section = key if not value else None
            if key == "schema":
                if schema is not None or not value:
                    raise RuntimeError(
                        "tracked Foundation data manifest schema is ambiguous"
                    )
                schema = value
            continue
        if (
            current_section not in roles
            or not raw_line.startswith("  ")
            or raw_line.startswith("    ")
        ):
            continue
        key, separator, raw_value = raw_line[2:].partition(":")
        if not separator:
            if current_section == "observed_development":
                raise RuntimeError(
                    "tracked Foundation observed development is malformed"
                )
            continue
        approved = (
            _OBSERVED_DEVELOPMENT_FIELDS
            if current_section == "observed_development"
            else frozenset({"path", "sha256"})
        )
        if key not in approved:
            if current_section == "observed_development":
                raise RuntimeError(
                    "tracked Foundation observed development fields differ"
                )
            continue
        value = _foundation_scalar(raw_value)
        if not value or key in roles[current_section]:
            raise RuntimeError(
                f"Foundation protected input field is ambiguous: {current_section}.{key}"
            )
        roles[current_section][key] = value
    return {"schema": schema, **roles}


def _foundation_scalar(raw_value: str) -> str:
    value = raw_value.strip()
    if not value:
        return value
    if value.startswith('"') or value.endswith('"'):
        if not (len(value) >= 2 and value.startswith('"') and value.endswith('"')):
            raise RuntimeError("tracked Foundation quoted scalar is malformed")
        value = value[1:-1]
        if (
            not value
            or '"' in value
            or "\\" in value
            or any(ord(character) < 32 or ord(character) > 126 for character in value)
        ):
            raise RuntimeError("tracked Foundation quoted scalar is unsupported")
    return value


def _protected_development_input_plan(
    root: Path, *, index_tree: str, tracked_paths: set[str]
) -> dict[str, object]:
    """Bind only Foundation-declared protected development test prerequisites."""

    if _FOUNDATION_DATA_PATH not in tracked_paths:
        return {
            "authority": "none",
            "input_count": 0,
            "inputs": [],
            "schema": "protected_development_inputs.v2",
            "scientific_or_claim_authority": False,
            "test_execution_prerequisite_only": True,
        }
    content = _tree_blob(root, index_tree, _FOUNDATION_DATA_PATH)
    try:
        text = content.decode("ascii")
    except UnicodeDecodeError as exc:
        raise RuntimeError(
            "tracked Foundation data manifest is not valid ASCII YAML"
        ) from exc
    document = _protected_foundation_fields(text)
    if document.get("schema") != "data_foundation":
        raise RuntimeError("tracked Foundation data manifest schema differs")
    observed_specification = document.get("observed_development")
    if not isinstance(observed_specification, dict) or set(
        observed_specification
    ) != _OBSERVED_DEVELOPMENT_FIELDS:
        raise RuntimeError(
            "Foundation observed development block is absent or malformed"
        )
    if (
        observed_specification.get("derivation")
        != _OBSERVED_DEVELOPMENT_DERIVATION
    ):
        raise RuntimeError("Foundation observed development derivation differs")
    for field in ("parent_dataset_sha256", "split_artifact_sha256"):
        value = observed_specification.get(field)
        if (
            type(value) is not str
            or len(value) != 64
            or value != value.lower()
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise RuntimeError(
                f"Foundation observed development {field} is invalid"
            )
    for field in ("byte_count", "row_count"):
        value = observed_specification.get(field)
        if (
            type(value) is not str
            or not value.isdigit()
            or str(int(value)) != value
            or int(value) <= 0
        ):
            raise RuntimeError(
                f"Foundation observed development {field} is invalid"
            )
    for field in ("first_time", "last_time"):
        value = observed_specification.get(field)
        if type(value) is not str or len(value) != 19 or not value.isascii():
            raise RuntimeError(
                f"Foundation observed development {field} is invalid"
            )
    split_specification = document.get("split_artifact")
    if not isinstance(split_specification, dict):
        raise RuntimeError("Foundation protected input role is absent: split_artifact")
    if (
        split_specification.get("sha256")
        != observed_specification.get("split_artifact_sha256")
    ):
        raise RuntimeError(
            "Foundation observed development names a different split artifact"
        )

    entries: list[dict[str, object]] = []
    seen_paths: set[str] = set()
    for role, _ in _PROTECTED_INPUT_RULES:
        specification = document.get(role)
        if not isinstance(specification, dict):
            raise RuntimeError(f"Foundation protected input role is absent: {role}")
        relative = _protected_relative_path(role, specification.get("path"))
        relative_text = relative.as_posix()
        expected = specification.get("sha256")
        if (
            type(expected) is not str
            or len(expected) != 64
            or expected != expected.lower()
            or any(character not in "0123456789abcdef" for character in expected)
        ):
            raise RuntimeError(
                f"Foundation protected input SHA256 is invalid: {role}"
            )
        if relative_text in seen_paths:
            raise RuntimeError("Foundation protected input paths are not unique")
        seen_paths.add(relative_text)
        candidate = _protected_repository_file(root, role, relative_text)
        observed, size = _hash_file(candidate)
        if observed != expected:
            raise RuntimeError(
                f"Foundation protected input SHA256 differs: {role}"
            )
        if role == "observed_development" and size != int(
            str(specification.get("byte_count"))
        ):
            raise RuntimeError(
                "Foundation observed development byte count differs"
            )
        entries.append(
            {
                "path": relative_text,
                "role": role,
                "sha256": expected,
                "size": size,
            }
        )
    foundation_blob = _tree_blob_id(root, index_tree, _FOUNDATION_DATA_PATH)
    return {
        "authority": "foundation_declared_protected_input",
        "foundation_blob": foundation_blob,
        "foundation_path": _FOUNDATION_DATA_PATH,
        "foundation_sha256": sha256(content).hexdigest(),
        "input_count": len(entries),
        "inputs": entries,
        "materialization": "verified_independent_read_only_copy",
        "schema": "protected_development_inputs.v2",
        "scientific_or_claim_authority": False,
        "test_execution_prerequisite_only": True,
    }


def _test_evidence_input_plan(
    root: Path, *, index_tree: str, tracked_paths: set[str]
) -> dict[str, object]:
    """Bind the exact small local evidence set required by tracked tests."""

    if _TEST_EVIDENCE_MANIFEST_PATH not in tracked_paths:
        return {
            "authority": "none",
            "input_count": 0,
            "inputs": [],
            "schema": "tracked_test_evidence_inputs.v1",
            "scientific_or_claim_authority": False,
            "test_execution_prerequisite_only": True,
        }
    content = _tree_blob(root, index_tree, _TEST_EVIDENCE_MANIFEST_PATH)
    try:
        text = content.decode("ascii")
    except UnicodeDecodeError as exc:
        raise RuntimeError("tracked test evidence manifest is not ASCII") from exc
    identities = tuple(text.splitlines())
    if (
        not text.endswith("\n")
        or not identities
        or len(identities) > _MAX_TEST_EVIDENCE_INPUTS
        or identities != tuple(sorted(set(identities)))
        or any(
            len(identity) != 64
            or identity != identity.lower()
            or any(
                character not in "0123456789abcdef"
                for character in identity
            )
            for identity in identities
        )
    ):
        raise RuntimeError("tracked test evidence manifest is malformed")
    entries: list[dict[str, object]] = []
    total_size = 0
    for identity in identities:
        relative = (
            _TEST_EVIDENCE_PREFIX / identity[:2] / identity
        ).as_posix()
        source = _protected_repository_file(
            root, _TEST_EVIDENCE_ROLE, relative
        )
        observed, size = _hash_file(source)
        if observed != identity:
            raise RuntimeError(
                "tracked test evidence content identity differs"
            )
        if size > _MAX_TEST_EVIDENCE_FILE_BYTES:
            raise RuntimeError("tracked test evidence file exceeds its bound")
        total_size += size
        if total_size > _MAX_TEST_EVIDENCE_TOTAL_BYTES:
            raise RuntimeError("tracked test evidence set exceeds its bound")
        entries.append(
            {
                "path": relative,
                "role": _TEST_EVIDENCE_ROLE,
                "sha256": identity,
                "size": size,
            }
        )
    return {
        "authority": "tracked_exact_content_allowlist",
        "input_count": len(entries),
        "inputs": entries,
        "manifest_blob": _tree_blob_id(
            root, index_tree, _TEST_EVIDENCE_MANIFEST_PATH
        ),
        "manifest_path": _TEST_EVIDENCE_MANIFEST_PATH,
        "manifest_sha256": sha256(content).hexdigest(),
        "materialization": "verified_independent_read_only_copy",
        "schema": "tracked_test_evidence_inputs.v1",
        "scientific_or_claim_authority": False,
        "test_execution_prerequisite_only": True,
        "total_size": total_size,
    }


def _runtime_projection_plan(tracked: set[str]) -> dict[str, str]:
    """Describe deterministic projection preparation without ignored inputs."""

    has_journal = "records/journal.jsonl" in tracked or (
        "records/journal/manifest.json" in tracked
        and any(
            path.startswith("records/journal/journal-")
            and path.endswith(".jsonl")
            for path in tracked
        )
    )
    if _PROJECTION_REBUILD_REQUIREMENTS.issubset(tracked) and has_journal:
        return {
            "authority": "git_index_tree_journal",
            "mode": "explicit_recovery",
        }
    return {"authority": "none", "mode": "none"}


def _sanitized_host_environment() -> dict[str, str]:
    environment = {
        key.upper(): value
        for key, value in os.environ.items()
        if key.upper() in _HOST_ENVIRONMENT_ALLOWLIST
    }
    paths: list[str] = []
    for candidate in (
        Path(sys.executable).resolve().parent,
        (
            Path(git_executable).resolve().parent
            if (git_executable := shutil.which("git")) is not None
            else None
        ),
        (
            Path(environment["SYSTEMROOT"]) / "System32"
            if "SYSTEMROOT" in environment
            else None
        ),
    ):
        if candidate is not None and str(candidate) not in paths:
            paths.append(str(candidate))
    environment["PATH"] = os.pathsep.join(paths)
    return environment


def _git_environment() -> dict[str, str]:
    """Keep normal Git attributes while dropping direct repository overrides."""

    environment = os.environ.copy()
    for key in tuple(environment):
        if key.upper().startswith("GIT_"):
            environment.pop(key, None)
    environment["GIT_TERMINAL_PROMPT"] = "0"
    return environment


def _isolated_git_environment() -> dict[str, str]:
    """Run sandbox Git without caller config, object, or repository overrides."""

    environment = _sanitized_host_environment()
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_TERMINAL_PROMPT"] = "0"
    return environment


def _runtime_discovery_environment() -> dict[str, str]:
    """Expose only host location inputs needed by trusted ``site`` discovery."""

    environment = _sanitized_host_environment()
    for key in ("APPDATA", "LOCALAPPDATA", "USERPROFILE", "HOMEDRIVE", "HOMEPATH"):
        value = os.environ.get(key)
        if value:
            environment[key] = value
    return environment


def _inherited_isolated_runtime_paths() -> tuple[str, ...]:
    """Reuse only runtime roots already bound by an independent parent run."""

    if os.environ.get("AXIOM_TRACKED_TEST_PARENT_RUNTIME") != "1":
        return ()
    if (
        os.environ.get("PYTHONSAFEPATH") != "1"
        or os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD") != "1"
    ):
        return ()
    try:
        project = PROJECT_ROOT.resolve(strict=True)
        if (
            _git(project, "remote").strip()
            or _git(project, "log", "-1", "--format=%s").decode("utf-8").strip()
            != "Isolated tracked-test snapshot"
            or _git(project, "rev-parse", "HEAD^{tree}").strip()
            != _git(project, "write-tree").strip()
            or (project / ".git" / "objects" / "info" / "alternates").exists()
        ):
            return ()
    except (
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        UnicodeDecodeError,
    ):
        return ()
    raw_paths = os.environ.get("PYTHONPATH", "").split(os.pathsep)
    if len(raw_paths) < 3:
        return ()
    try:
        resolved = tuple(str(Path(path).resolve(strict=True)) for path in raw_paths)
    except OSError:
        return ()
    if resolved[:2] != (str((project / "src").resolve()), str(project)):
        return ()
    inherited = tuple(dict.fromkeys(resolved[2:]))
    if not inherited or any(not Path(path).is_dir() for path in inherited):
        return ()
    return inherited


@lru_cache(maxsize=1)
def _distribution_search_paths() -> tuple[str, ...]:
    """Find default install roots without honoring caller Python overrides."""

    completed = subprocess.run(
        (
            sys.executable,
            "-E",
            "-s",
            "-P",
            "-c",
            "import site; print(site.getusersitepackages())",
        ),
        env=_runtime_discovery_environment(),
        check=True,
        capture_output=True,
        text=True,
        timeout=_LOCAL_SUBPROCESS_TIMEOUT_SECONDS,
    )
    ordered = (
        *_inherited_isolated_runtime_paths(),
        completed.stdout.strip(),
        sysconfig.get_path("purelib"),
        sysconfig.get_path("platlib"),
    )
    result: list[str] = []
    for path in ordered:
        if not path:
            continue
        candidate = Path(path)
        if not candidate.is_dir():
            continue
        resolved = str(candidate.resolve())
        if resolved not in result:
            result.append(resolved)
    return tuple(result)


def _python_runtime() -> tuple[dict[str, object], tuple[str, ...]]:
    """Bind the no-site dependency roots used by recovery and pytest."""

    roots = _distribution_search_paths()
    inventory: list[dict[str, object]] = []
    pytest_present = False
    for ordinal, root in enumerate(roots):
        for distribution in metadata.distributions(path=[root]):
            name = distribution.metadata.get("Name")
            if type(name) is not str or not name:
                continue
            normalized = name.lower().replace("_", "-")
            pytest_present = pytest_present or normalized == "pytest"
            # ``Distribution.files`` parses the whole RECORD and stats every
            # installed file before returning its paths.  On the research
            # runtime that means more than 60,000 filesystem probes for every
            # focused test invocation even though this manifest binds only the
            # distribution RECORD.  ``read_text`` is the public direct metadata
            # boundary and avoids turning environment attestation into the
            # dominant validation cost.  Its documented text boundary may
            # normalize platform newlines, so name the digest for those text
            # semantics instead of claiming a raw-file byte digest.
            record = distribution.read_text("RECORD")
            record_digest = (
                None
                if record is None
                else sha256(record.encode("utf-8")).hexdigest()
            )
            inventory.append(
                {
                    "distribution": normalized,
                    "record_text_sha256": record_digest,
                    "root_ordinal": ordinal,
                    "version": distribution.version,
                }
            )
    inventory.sort(
        key=lambda value: (
            value["root_ordinal"],
            value["distribution"],
            value["version"],
        )
    )
    if not pytest_present:
        raise RuntimeError("pytest runtime distribution is absent")
    body: dict[str, object] = {
        "distribution_count": len(inventory),
        "inventory": inventory,
        "mode": "sanitized_distribution_roots_no_site",
        "root_count": len(roots),
    }
    return {
        **body,
        "runtime_sha256": sha256(canonical_bytes(body)).hexdigest(),
    }, roots


def _manifest(
    root: Path,
    *,
    pytest_args: Sequence[str],
    selectors: Sequence[str] = (),
    execution_timeout_seconds: int | None = None,
    rebuild_runtime_projection: bool = False,
    rebuild_runtime_projection_from_head_authority: bool = False,
) -> tuple[dict[str, object], tuple[str, ...], tuple[str, ...]]:
    top = Path(
        _git(root, "rev-parse", "--show-toplevel").decode("utf-8").strip()
    ).resolve()
    if top != root:
        raise RuntimeError("tracked-test root differs from the Git repository root")
    head = _git(root, "rev-parse", "HEAD").decode("ascii").strip()
    index_tree = _git(root, "write-tree").decode("ascii").strip()
    tracked_paths = set(_tree_paths(root, index_tree))
    tracked = tuple(
        path
        for path in sorted(tracked_paths)
        if path.startswith("tests/")
        if _is_pytest_file(path)
    )
    untracked = tuple(
        path
        for path in _paths(
            _git(
                root,
                "ls-files",
                "--others",
                "--exclude-standard",
                "-z",
                "--",
                "tests",
            )
        )
        if _is_pytest_file(path)
    )
    if not tracked:
        raise RuntimeError("tracked-test manifest is empty")
    focused = _validate_test_selection(selectors, tracked=tracked)
    execution_timeout_seconds = _validate_execution_timeout(
        (
            _DEFAULT_FOCUSED_PYTEST_TIMEOUT_SECONDS
            if focused
            else _DEFAULT_FULL_PYTEST_TIMEOUT_SECONDS
        )
        if execution_timeout_seconds is None
        else execution_timeout_seconds
    )
    selected = focused or tracked
    available_runtime_projection = _runtime_projection_plan(tracked_paths)
    if rebuild_runtime_projection and rebuild_runtime_projection_from_head_authority:
        raise RuntimeError("runtime projection recovery modes are mutually exclusive")
    if rebuild_runtime_projection_from_head_authority and not focused:
        raise RuntimeError("HEAD authority transition requires a focused selection")
    if rebuild_runtime_projection and available_runtime_projection == {
        "authority": "none",
        "mode": "none",
    }:
        raise RuntimeError(
            "focused runtime projection rebuild lacks indexed Journal authority"
        )
    if rebuild_runtime_projection_from_head_authority:
        if available_runtime_projection["authority"] == "none":
            raise RuntimeError("HEAD authority transition lacks indexed Journal")
        runtime_projection = _head_authority_transition_plan(
            root,
            head=head,
            index_tree=index_tree,
            index_paths=tracked_paths,
        )
    else:
        runtime_projection = (
            available_runtime_projection
            if not focused or rebuild_runtime_projection
            else {
                "authority": "none",
                "mode": "focused_no_recovery",
            }
        )
    selected_files = tuple(
        sorted({value.split("::", 1)[0] for value in selected})
    )
    for path in selected_files:
        try:
            (root / Path(path)).read_bytes()
        except OSError as exc:
            raise RuntimeError(f"selected tracked test is unavailable: {path}") from exc
    selected_blobs = _tree_test_blob_ids(root, index_tree, selected_files)
    selected_worktree_blobs = _worktree_blob_ids(root, selected_files)
    for path, blob, worktree_blob in zip(
        selected_files,
        selected_blobs,
        selected_worktree_blobs,
        strict=True,
    ):
        if worktree_blob != blob:
            raise RuntimeError(
                "selected tracked test worktree bytes differ from the Git "
                "index blob: " + path
            )
    blobs = _tree_test_blob_ids(root, index_tree, tracked)
    contents = _batch_blob_contents(root, blobs)
    entries: list[dict[str, str]] = []
    for path, blob, content in zip(
        tracked,
        blobs,
        contents,
        strict=True,
    ):
        entries.append(
            {"blob": blob, "path": path, "sha256": sha256(content).hexdigest()}
        )
    protected_inputs = _protected_development_input_plan(
        root, index_tree=index_tree, tracked_paths=tracked_paths
    )
    test_evidence_inputs = _test_evidence_input_plan(
        root, index_tree=index_tree, tracked_paths=tracked_paths
    )
    python_runtime, runtime_paths = _python_runtime()
    body: dict[str, object] = {
        "execution_mode": "isolated_git_index_tree",
        "excluded_untracked_test_count": len(untracked),
        "excluded_untracked_tests": list(untracked),
        "execution_timeout_seconds": execution_timeout_seconds,
        "git_head": head,
        "git_index_tree": index_tree,
        "protected_development_inputs": protected_inputs,
        "pytest_args": list(pytest_args),
        "python_runtime": python_runtime,
        "runtime_projection": runtime_projection,
        "sandbox_origin_policy": "detached_no_remote_no_push",
        "schema": "tracked_pytest_manifest.v3",
        "selection": {
            "authority": "subset_of_frozen_git_index_test_manifest",
            "mode": "focused" if focused else "all_tracked",
            "selected_tracked_file_count": len(
                {value.split("::", 1)[0] for value in selected}
            ),
            "selectors": list(focused),
            "unselected_tracked_file_count": len(tracked)
            - len({value.split("::", 1)[0] for value in selected}),
        },
        "test_evidence_inputs": test_evidence_inputs,
        "tracked_test_count": len(entries),
        "tracked_tests": entries,
    }
    observed_head = _git(root, "rev-parse", "HEAD").decode("ascii").strip()
    observed_tree = _git(root, "write-tree").decode("ascii").strip()
    if observed_head != head or observed_tree != index_tree:
        raise RuntimeError(
            "HEAD or Git index changed during tracked-test manifest construction"
        )
    return (
        {
            **body,
            "manifest_sha256": sha256(canonical_bytes(body)).hexdigest(),
        },
        selected,
        runtime_paths,
    )


def _isolated_environment(
    repository: Path,
    *,
    runtime_root: Path,
    runtime_paths: Sequence[str],
) -> dict[str, str]:
    repository = repository.resolve()
    runtime_root = runtime_root.resolve()
    if (
        repository == runtime_root
        or repository in runtime_root.parents
        or runtime_root in repository.parents
        or repository.parent != runtime_root.parent
    ):
        raise RuntimeError(
            "isolated runtime root must be a repository sibling"
        )
    environment = _sanitized_host_environment()
    home = runtime_root / "home"
    temporary = runtime_root / "tmp"
    appdata = home / "AppData" / "Roaming"
    local_appdata = home / "AppData" / "Local"
    for directory in (home, temporary, appdata, local_appdata):
        directory.mkdir(parents=True, exist_ok=True)
    environment["HOME"] = str(home)
    environment["USERPROFILE"] = str(home)
    environment["TEMP"] = str(temporary)
    environment["TMP"] = str(temporary)
    environment["APPDATA"] = str(appdata)
    environment["LOCALAPPDATA"] = str(local_appdata)
    environment["AXIOM_TRACKED_TEST_PARENT_RUNTIME"] = "1"
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    # The exact index-tree root is required for intentional ``tests.*``
    # imports.  The sandbox contains no source-worktree untracked files.
    python_paths: list[str | Path] = [
        repository / "src",
        repository,
        *runtime_paths,
    ]
    environment["PYTHONPATH"] = os.pathsep.join(str(path) for path in python_paths)
    environment["PYTHONSAFEPATH"] = "1"
    return environment


def _transition_entries(plan: Mapping[str, object]) -> tuple[dict[str, str], ...]:
    declared = plan.get("control_declared_authority_paths")
    raw_entries = plan.get("temporary_authority_paths")
    if (
        plan.get("mode") != _HEAD_AUTHORITY_TRANSITION_MODE
        or plan.get("authority") != _HEAD_AUTHORITY_TRANSITION_AUTHORITY
        or not isinstance(declared, list)
        or not isinstance(raw_entries, list)
    ):
        raise RuntimeError("HEAD authority transition plan is invalid")
    entries: list[dict[str, str]] = []
    for raw in raw_entries:
        if (
            not isinstance(raw, dict)
            or set(raw)
            != {"head_blob", "head_sha256", "index_blob", "index_sha256", "path"}
            or raw.get("path") not in declared
            or any(type(value) is not str for value in raw.values())
        ):
            raise RuntimeError("HEAD transition path is outside control authority")
        entry = dict(raw)
        if any(
            len(entry[key]) != 64
            or any(character not in "0123456789abcdef" for character in entry[key])
            for key in ("head_sha256", "index_sha256")
        ):
            raise RuntimeError("HEAD authority transition hash is invalid")
        entries.append(entry)
    paths = tuple(entry["path"] for entry in entries)
    if not entries or paths != tuple(sorted(set(paths))):
        raise RuntimeError("HEAD authority transition paths are not exact")
    return tuple(entries)


def _rebuild_runtime_projection(
    sandbox: Path,
    *,
    runtime_root: Path,
    runtime_paths: Sequence[str],
    subprocess_timeout_seconds: float,
    declared_execution_timeout_seconds: int,
    require_clean_git: bool = True,
) -> None:
    """Rebuild disposable SQLite state from the checked-out Journal authority."""

    try:
        completed = subprocess.run(
            (
                sys.executable,
                "-S",
                "-s",
                "-P",
                "-m",
                "axiom_rift.cli",
                "--root",
                str(sandbox),
                "recover",
            ),
            cwd=sandbox,
            env=_isolated_environment(
                sandbox,
                runtime_root=runtime_root,
                runtime_paths=runtime_paths,
            ),
            check=False,
            capture_output=True,
            timeout=subprocess_timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "isolated Journal projection rebuild exceeded its bound of "
            f"{declared_execution_timeout_seconds} seconds"
        ) from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            "isolated Journal projection rebuild failed"
            + (f": {detail[-1000:]}" if detail else "")
        )
    try:
        report = json.loads(completed.stdout.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "isolated Journal projection rebuild returned an invalid report"
        ) from exc
    if not isinstance(report, dict) or report.get("schema") != "axiom_recovery":
        raise RuntimeError(
            "isolated Journal projection rebuild report schema differs"
        )
    if require_clean_git and (
        subprocess.run(
            ("git", "diff", "--quiet", "--"),
            cwd=sandbox,
            check=False,
            capture_output=True,
            timeout=_LOCAL_SUBPROCESS_TIMEOUT_SECONDS,
        ).returncode
        != 0
    ):
        raise RuntimeError(
            "isolated Journal projection rebuild changed tracked authority bytes"
        )


def _rebuild_runtime_projection_from_head_authority(
    root: Path,
    sandbox: Path,
    *,
    plan: Mapping[str, object],
    runtime_root: Path,
    runtime_paths: Sequence[str],
    subprocess_timeout_seconds: float,
    declared_execution_timeout_seconds: int,
) -> None:
    entries = _transition_entries(plan)
    head_contents = _batch_blob_contents(
        root, tuple(entry["head_blob"] for entry in entries)
    )
    index_contents = _batch_blob_contents(
        root, tuple(entry["index_blob"] for entry in entries)
    )
    swapped = 0
    try:
        sandbox_tree = _git(sandbox, "rev-parse", "HEAD^{tree}").decode("ascii").strip()
        if sandbox_tree != plan.get("prospective_git_index_tree") or _worktree_blob_ids(
            sandbox, tuple(entry["path"] for entry in entries)
        ) != tuple(entry["index_blob"] for entry in entries):
            raise RuntimeError("HEAD transition sandbox authority differs")
        for entry, historical, prospective in zip(
            entries, head_contents, index_contents, strict=True
        ):
            if (
                sha256(historical).hexdigest() != entry["head_sha256"]
                or sha256(prospective).hexdigest() != entry["index_sha256"]
            ):
                raise RuntimeError("HEAD transition frozen bytes differ")
            replace_stable_regular_file(
                sandbox / Path(entry["path"]),
                historical,
                require_existing=True,
                expected_current_sha256=_hash_file(
                    sandbox / Path(entry["path"])
                )[0],
            )
            swapped += 1
        dirty = tuple(sorted(_paths(_git(sandbox, "diff", "--name-only", "-z", "--"))))
        if dirty != tuple(entry["path"] for entry in entries):
            raise RuntimeError("HEAD transition changed an undeclared path")
        _rebuild_runtime_projection(
            sandbox,
            runtime_root=runtime_root,
            runtime_paths=runtime_paths,
            subprocess_timeout_seconds=subprocess_timeout_seconds,
            declared_execution_timeout_seconds=declared_execution_timeout_seconds,
            require_clean_git=False,
        )
    finally:
        for ordinal in reversed(range(swapped)):
            entry = entries[ordinal]
            replace_stable_regular_file(
                sandbox / Path(entry["path"]),
                index_contents[ordinal],
                require_existing=True,
                expected_current_sha256=entry["head_sha256"],
            )
        if swapped:
            _git(
                sandbox,
                "checkout-index",
                "--force",
                "--",
                *(entry["path"] for entry in entries[:swapped]),
            )
    for arguments in (("diff", "--quiet", "--"), ("diff", "--cached", "--quiet", "--")):
        if subprocess.run(
            ("git", *arguments),
            cwd=sandbox,
            check=False,
            capture_output=True,
            timeout=_LOCAL_SUBPROCESS_TIMEOUT_SECONDS,
        ).returncode:
            raise RuntimeError("HEAD transition did not restore a clean index tree")


def _validated_protected_entry(value: object) -> dict[str, object]:
    required = {"path", "role", "sha256", "size"}
    if not isinstance(value, Mapping) or set(value) != required:
        raise RuntimeError("protected input manifest entry is malformed")
    role = value.get("role")
    if type(role) is not str or role not in dict(_MATERIALIZED_INPUT_RULES):
        raise RuntimeError("protected input manifest role is invalid")
    relative = _protected_relative_path(role, value.get("path"))
    digest = value.get("sha256")
    size = value.get("size")
    if (
        type(digest) is not str
        or len(digest) != 64
        or digest != digest.lower()
        or any(character not in "0123456789abcdef" for character in digest)
        or type(size) is not int
        or size < 0
    ):
        raise RuntimeError("protected input manifest identity is invalid")
    return {
        "path": relative.as_posix(),
        "role": role,
        "sha256": digest,
        "size": size,
    }


def _prepare_destination_file(sandbox: Path, relative: PurePosixPath) -> Path:
    destination = sandbox.joinpath(*relative.parts)
    try:
        ensure_link_free_directory_chain(destination.parent)
        destination.lstat()
    except FileNotFoundError:
        return destination
    except PathBoundaryError as exc:
        raise RuntimeError(
            "protected input sandbox destination crosses a link-like directory"
        ) from exc
    except OSError as exc:
        raise RuntimeError(
            "protected input sandbox destination is unavailable"
        ) from exc
    else:
        raise RuntimeError("protected input sandbox destination already exists")


def _exclusive_regular_file(path: Path) -> tuple[int, os.stat_result]:
    """Create one private regular file without following an existing leaf."""

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, stat.S_IRUSR | stat.S_IWUSR)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise RuntimeError(
                "protected input sandbox destination is not a private regular file"
            )
        visible = path.lstat()
        if (
            visible.st_dev,
            visible.st_ino,
            visible.st_nlink,
        ) != (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_nlink,
        ):
            raise RuntimeError(
                "protected input sandbox destination identity changed"
            )
        return descriptor, metadata
    except BaseException:
        os.close(descriptor)
        try:
            visible = path.lstat()
            if (
                "metadata" in locals()
                and (visible.st_dev, visible.st_ino)
                == (metadata.st_dev, metadata.st_ino)
            ):
                path.unlink()
        except OSError:
            pass
        raise


def _make_exact_materialized_file_writable(
    path: Path, identity: tuple[int, int] | None = None
) -> bool:
    """Use an opened descriptor so cleanup never chmods a link replacement."""

    try:
        visible = path.lstat()
    except FileNotFoundError:
        return False
    if identity is not None and (visible.st_dev, visible.st_ino) != identity:
        return False
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return False
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino)
            != (visible.st_dev, visible.st_ino)
        ):
            return False
        os.fchmod(descriptor, stat.S_IRUSR | stat.S_IWUSR)
        return True
    finally:
        os.close(descriptor)


def _remove_exact_materialized_file(
    path: Path, identity: tuple[int, int]
) -> None:
    """Best-effort cleanup without chmod or unlink of a replacement path."""

    try:
        visible = path.lstat()
    except FileNotFoundError:
        return
    if (visible.st_dev, visible.st_ino) != identity:
        return
    if not _make_exact_materialized_file_writable(path, identity):
        return
    try:
        visible = path.lstat()
        if (visible.st_dev, visible.st_ino) == identity:
            path.unlink()
    except OSError:
        pass


def _copy_protected_input(
    root: Path, sandbox: Path, value: object
) -> dict[str, object]:
    entry = _validated_protected_entry(value)
    role = str(entry["role"])
    source = _protected_repository_file(root, role, entry["path"])
    destination = _prepare_destination_file(
        sandbox, PurePosixPath(str(entry["path"]))
    )
    digest = sha256()
    copied = 0
    destination_identity: tuple[int, int] | None = None
    try:
        require_link_free_directory_chain(destination.parent)
        descriptor, created = _exclusive_regular_file(destination)
        destination_identity = (created.st_dev, created.st_ino)
        with source.open("rb") as source_handle, os.fdopen(
            descriptor, "wb"
        ) as target:
            before = os.fstat(source_handle.fileno())
            source_visible_before = source.lstat()
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or (
                    before.st_dev,
                    before.st_ino,
                    before.st_size,
                    before.st_mtime_ns,
                    before.st_nlink,
                )
                != (
                    source_visible_before.st_dev,
                    source_visible_before.st_ino,
                    source_visible_before.st_size,
                    source_visible_before.st_mtime_ns,
                    source_visible_before.st_nlink,
                )
            ):
                raise RuntimeError(
                    "protected input source is not one exact regular file"
                )
            while True:
                chunk = source_handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                copied += len(chunk)
                if target.write(chunk) != len(chunk):
                    raise RuntimeError("protected input materialization was truncated")
            target.flush()
            os.fsync(target.fileno())
            after = os.fstat(source_handle.fileno())
            target_after = os.fstat(target.fileno())
            source_visible_after = source.lstat()
            destination_visible = destination.lstat()
            require_link_free_directory_chain(destination.parent)
            if (
                not stat.S_ISREG(target_after.st_mode)
                or target_after.st_nlink != 1
                or (target_after.st_dev, target_after.st_ino)
                != (destination_visible.st_dev, destination_visible.st_ino)
                or target_after.st_size != copied
            ):
                raise RuntimeError(
                    "protected input sandbox destination identity changed"
                )
            os.fchmod(
                target.fileno(), stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
            )
        source_identity = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_nlink,
        )
        if source_identity != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_nlink,
        ) or source_identity != (
            source_visible_after.st_dev,
            source_visible_after.st_ino,
            source_visible_after.st_size,
            source_visible_after.st_mtime_ns,
            source_visible_after.st_nlink,
        ):
            raise RuntimeError("protected input changed during materialization")
        if digest.hexdigest() != entry["sha256"] or copied != entry["size"]:
            raise RuntimeError("protected input changed before materialization")
    except Exception:
        if destination_identity is not None:
            _remove_exact_materialized_file(destination, destination_identity)
        raise
    return entry


def _materialize_protected_inputs(
    root: Path,
    sandbox: Path,
    *,
    protected_inputs: Sequence[object],
) -> tuple[dict[str, object], ...]:
    validated = tuple(_validated_protected_entry(value) for value in protected_inputs)
    expected_roles = tuple(role for role, _ in _PROTECTED_INPUT_RULES)
    observed_roles = tuple(str(entry["role"]) for entry in validated)
    foundation_roles = tuple(
        role for role in observed_roles if role != _TEST_EVIDENCE_ROLE
    )
    evidence_entries = tuple(
        entry
        for entry in validated
        if entry["role"] == _TEST_EVIDENCE_ROLE
    )
    if foundation_roles and foundation_roles != expected_roles:
        raise RuntimeError(
            "protected input manifest must contain the exact approved role set"
        )
    expected_observed_roles = (
        *foundation_roles,
        *(_TEST_EVIDENCE_ROLE for _ in evidence_entries),
    )
    if observed_roles != expected_observed_roles:
        raise RuntimeError("test evidence inputs must follow Foundation inputs")
    evidence_paths = tuple(str(entry["path"]) for entry in evidence_entries)
    if evidence_paths != tuple(sorted(set(evidence_paths))):
        raise RuntimeError("test evidence input paths are not canonical")
    paths = tuple(str(entry["path"]) for entry in validated)
    if len(set(paths)) != len(paths):
        raise RuntimeError("protected input manifest paths are not unique")
    materialized: list[dict[str, object]] = []
    try:
        for value in validated:
            entry = _copy_protected_input(root, sandbox, value)
            materialized.append(entry)
    except BaseException:
        _restore_materialized_permissions(sandbox, materialized)
        raise
    return tuple(materialized)


def _verify_protected_sources(
    root: Path, entries: Sequence[Mapping[str, object]]
) -> None:
    for value in entries:
        entry = _validated_protected_entry(value)
        source = _protected_repository_file(
            root, str(entry["role"]), entry["path"]
        )
        observed, size = _hash_file(source)
        if observed != entry["sha256"] or size != entry["size"]:
            raise RuntimeError("protected input source changed during isolated pytest")


def _verify_materialized_destinations(
    sandbox: Path, entries: Sequence[Mapping[str, object]]
) -> None:
    for value in entries:
        entry = _validated_protected_entry(value)
        destination = _protected_repository_file(
            sandbox, str(entry["role"]), entry["path"]
        )
        metadata = destination.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
        ):
            raise RuntimeError("materialized protected input became writable")
        observed, size = _hash_file(destination)
        if observed != entry["sha256"] or size != entry["size"]:
            raise RuntimeError("materialized protected input changed during isolated pytest")


def _restore_materialized_permissions(
    sandbox: Path, entries: Sequence[Mapping[str, object]]
) -> None:
    for value in entries:
        try:
            entry = _validated_protected_entry(value)
            destination = _protected_repository_file(
                sandbox, str(entry["role"]), entry["path"]
            )
            _make_exact_materialized_file_writable(destination)
        except (OSError, RuntimeError):
            # A missing or replaced path needs no permission repair.  Avoid
            # following an untrusted replacement during best-effort cleanup.
            continue


def _verify_independent_git_metadata(sandbox: Path, source_root: Path) -> None:
    git_directory = sandbox / ".git"
    if (
        _is_link_like(git_directory)
        or not git_directory.is_dir()
        or git_directory.resolve(strict=True).parent != sandbox
    ):
        raise RuntimeError("isolated Git metadata is not a confined directory")
    alternates = git_directory / "objects" / "info" / "alternates"
    if alternates.exists() or _is_link_like(alternates):
        raise RuntimeError("isolated Git metadata retains an object alternate")
    if _isolated_git(sandbox, "remote").strip():
        raise RuntimeError("isolated Git metadata retains a remote")
    needles = {
        str(source_root.resolve()).encode("utf-8").lower(),
        source_root.resolve().as_posix().encode("utf-8").lower(),
    }
    for current, directories, files in os.walk(git_directory, followlinks=False):
        current_path = Path(current)
        for name in directories:
            candidate = current_path / name
            if _is_link_like(candidate):
                raise RuntimeError("isolated Git metadata contains a link-like directory")
        for name in files:
            candidate = current_path / name
            if _is_link_like(candidate) or not candidate.is_file():
                raise RuntimeError("isolated Git metadata contains a link-like file")
            content = candidate.read_bytes().lower()
            if any(needle and needle in content for needle in needles):
                raise RuntimeError("isolated Git metadata exposes the source repository path")


def _checkout_independent_index_tree(
    root: Path, sandbox: Path, *, index_tree: str
) -> None:
    # Fail before materialization if the frozen tree contains links or other
    # non-regular entries.  The returned modes remain encoded in the tree and
    # are loaded directly into the independent index below.
    _regular_tree_modes(root, index_tree)
    object_format = (
        _git(root, "rev-parse", "--show-object-format").decode("ascii").strip()
    )
    if object_format not in {"sha1", "sha256"}:
        raise RuntimeError("source Git object format is unsupported")
    if sandbox.exists() or _is_link_like(sandbox):
        if (
            _is_link_like(sandbox)
            or not sandbox.is_dir()
            or any(sandbox.iterdir())
        ):
            raise RuntimeError("isolated Git destination is not an empty directory")
    else:
        sandbox.mkdir()
    _isolated_git(
        sandbox,
        "init",
        "--quiet",
        "--initial-branch=isolated",
        f"--object-format={object_format}",
        "--template=",
    )

    # Transfer only the frozen index tree and its reachable blobs.  A shared
    # clone followed by deleting .git and re-adding the whole worktree hashed
    # every large journal/data fixture twice on every focused run.  The pack is
    # self-contained: no alternate, remote, source path, or history is retained.
    packed = subprocess.run(
        ("git", "pack-objects", "--stdout", "--revs"),
        cwd=root,
        env=_isolated_git_environment(),
        input=f"{index_tree}\n".encode("ascii"),
        check=True,
        capture_output=True,
        timeout=_LOCAL_SUBPROCESS_TIMEOUT_SECONDS,
    ).stdout
    if not packed:
        raise RuntimeError("frozen index tree object pack is empty")
    subprocess.run(
        ("git", "index-pack", "--stdin", "--strict"),
        cwd=sandbox,
        env=_isolated_git_environment(),
        input=packed,
        check=True,
        capture_output=True,
        timeout=_LOCAL_SUBPROCESS_TIMEOUT_SECONDS,
    )
    _isolated_git(sandbox, "read-tree", index_tree)
    _isolated_git(sandbox, "checkout-index", "--all", "--force")
    observed_tree = _isolated_git(sandbox, "write-tree").decode("ascii").strip()
    if observed_tree != index_tree:
        raise RuntimeError("isolated pytest index tree differs")
    commit_environment = _isolated_git_environment()
    commit_environment.update(
        {
            "GIT_AUTHOR_EMAIL": "isolated-test@example.invalid",
            "GIT_AUTHOR_NAME": "Axiom Isolated Test",
            "GIT_COMMITTER_EMAIL": "isolated-test@example.invalid",
            "GIT_COMMITTER_NAME": "Axiom Isolated Test",
        }
    )
    commit = subprocess.run(
        ("git", "commit-tree", index_tree),
        cwd=sandbox,
        env=commit_environment,
        input=b"Isolated tracked-test snapshot\n",
        check=True,
        capture_output=True,
        timeout=_LOCAL_SUBPROCESS_TIMEOUT_SECONDS,
    ).stdout.decode("ascii").strip()
    if not commit:
        raise RuntimeError("independent Git snapshot commit is absent")
    _isolated_git(sandbox, "update-ref", "refs/heads/isolated", commit)
    committed_tree = (
        _isolated_git(sandbox, "rev-parse", "HEAD^{tree}").decode("ascii").strip()
    )
    if committed_tree != index_tree:
        raise RuntimeError("independent Git commit tree differs")
    _isolated_git(sandbox, "config", "core.hooksPath", ".githooks")
    _verify_independent_git_metadata(sandbox, root)


def _run_isolated_pytest(
    root: Path,
    *,
    index_tree: str,
    tracked: Sequence[str],
    pytest_args: Sequence[str],
    execution_timeout_seconds: int,
    rebuild_runtime_projection: bool,
    transition_plan: Mapping[str, object] | None = None,
    runtime_paths: Sequence[str],
    protected_inputs: Sequence[object] = (),
) -> int:
    execution_deadline = time.monotonic() + execution_timeout_seconds

    def remaining_timeout(stage: str) -> float:
        remaining = execution_deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(
                f"isolated {stage} exceeded its shared bound of "
                f"{execution_timeout_seconds} seconds"
            )
        return remaining

    with TemporaryDirectory(prefix="tracked-pytest-") as temporary:
        isolation_root = Path(temporary).resolve()
        sandbox = isolation_root / "repository"
        runtime_root = isolation_root / "runtime"
        if root == isolation_root or root in isolation_root.parents:
            raise RuntimeError("isolated pytest sandbox remains under the source repository")
        _checkout_independent_index_tree(root, sandbox, index_tree=index_tree)
        materialized = _materialize_protected_inputs(
            root,
            sandbox,
            protected_inputs=protected_inputs,
        )
        completed: subprocess.CompletedProcess[bytes] | None = None
        execution_error: BaseException | None = None
        postcondition_errors: list[BaseException] = []
        try:
            if transition_plan is not None:
                _rebuild_runtime_projection_from_head_authority(
                    root,
                    sandbox,
                    plan=transition_plan,
                    runtime_root=runtime_root,
                    runtime_paths=runtime_paths,
                    subprocess_timeout_seconds=remaining_timeout(
                        "HEAD authority projection transition"
                    ),
                    declared_execution_timeout_seconds=execution_timeout_seconds,
                )
            elif rebuild_runtime_projection:
                _rebuild_runtime_projection(
                    sandbox,
                    runtime_root=runtime_root,
                    runtime_paths=runtime_paths,
                    subprocess_timeout_seconds=remaining_timeout(
                        "Journal projection rebuild"
                    ),
                    declared_execution_timeout_seconds=(
                        execution_timeout_seconds
                    ),
                )
            completed = subprocess.run(
                (
                    sys.executable,
                    "-S",
                    "-s",
                    "-P",
                    "-m",
                    "pytest",
                    *pytest_args,
                    *tracked,
                ),
                cwd=sandbox,
                env=_isolated_environment(
                    sandbox,
                    runtime_root=runtime_root,
                    runtime_paths=runtime_paths,
                ),
                check=False,
                timeout=remaining_timeout("pytest"),
            )
        except BaseException as exc:
            execution_error = exc
        finally:
            for verification in (
                lambda: _verify_protected_sources(root, materialized),
                lambda: _verify_materialized_destinations(sandbox, materialized),
            ):
                try:
                    verification()
                except BaseException as exc:
                    postcondition_errors.append(exc)
            _restore_materialized_permissions(sandbox, materialized)
        if postcondition_errors:
            detail = "; ".join(str(error) for error in postcondition_errors)
            raise RuntimeError(
                f"protected input postcondition failed: {detail}"
            ) from (execution_error or postcondition_errors[0])
        if isinstance(execution_error, subprocess.TimeoutExpired):
            raise RuntimeError(
                "isolated pytest exceeded its bound of "
                f"{execution_timeout_seconds} seconds"
            ) from execution_error
        if execution_error is not None:
            raise execution_error
        if completed is None:
            raise RuntimeError("isolated pytest did not produce a completion")
        return completed.returncode


def _write_manifest(root: Path, output: Path, manifest: dict[str, object]) -> bool:
    local = Path(os.path.abspath(root / "local"))
    destination = Path(os.path.abspath(output))
    if local not in destination.parents:
        raise RuntimeError("manifest output must remain under local/")
    content = canonical_bytes(manifest) + b"\n"
    try:
        return publish_stable_regular_file_if_changed(destination, content)
    except AtomicFileError as exc:
        raise RuntimeError(
            f"tracked-test manifest publication failed: {exc}"
        ) from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Hash and run only Git-tracked tests. Untracked test files are "
            "reported and excluded by construction."
        )
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=PROJECT_ROOT,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--manifest-only",
        action="store_true",
        help="render the manifest without invoking pytest",
    )
    parser.add_argument(
        "--manifest-output",
        type=Path,
        help="write the canonical manifest below local/",
    )
    parser.add_argument(
        "--no-manifest-file",
        action="store_true",
        help="do not write the default local/tracked-test-manifest.json",
    )
    parser.add_argument(
        "--select",
        action="append",
        default=[],
        metavar="TRACKED_TEST[::NODE]",
        help=(
            "run an exact Git-index test file or identifier-only test node "
            "prefix; may be repeated"
        ),
    )
    parser.add_argument(
        "--execution-timeout-seconds",
        type=int,
        default=None,
        metavar="SECONDS",
        help=(
            "kill and fail an isolated pytest process that exceeds this bound; "
            f"defaults: focused={_DEFAULT_FOCUSED_PYTEST_TIMEOUT_SECONDS}, "
            f"all-tracked={_DEFAULT_FULL_PYTEST_TIMEOUT_SECONDS}"
        ),
    )
    parser.add_argument(
        "--rebuild-runtime-projection",
        action="store_true",
        help=(
            "for a focused selection, explicitly rebuild the ignored SQLite "
            "projection from indexed Journal authority"
        ),
    )
    parser.add_argument(
        "--rebuild-runtime-projection-from-head-authority",
        action="store_true",
        help=(
            "for a focused authority transition, recover with only the "
            "control-declared authority files temporarily restored from HEAD"
        ),
    )
    parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="arguments after -- are forwarded to pytest",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    root = arguments.repository_root.resolve()
    pytest_args = list(arguments.pytest_args)
    if pytest_args[:1] == ["--"]:
        pytest_args.pop(0)
    try:
        pytest_args = list(_validate_pytest_args(pytest_args))
        manifest, tracked, runtime_paths = _manifest(
            root,
            pytest_args=pytest_args,
            selectors=arguments.select,
            execution_timeout_seconds=arguments.execution_timeout_seconds,
            rebuild_runtime_projection=arguments.rebuild_runtime_projection,
            rebuild_runtime_projection_from_head_authority=(
                arguments.rebuild_runtime_projection_from_head_authority
            ),
        )
        protected_plan = manifest.get("protected_development_inputs")
        if not isinstance(protected_plan, dict) or not isinstance(
            protected_plan.get("inputs"), list
        ):
            raise RuntimeError("protected development input plan is malformed")
        test_evidence_plan = manifest.get("test_evidence_inputs")
        if not isinstance(test_evidence_plan, dict) or not isinstance(
            test_evidence_plan.get("inputs"), list
        ):
            raise RuntimeError("tracked test evidence input plan is malformed")
        protected_inputs = (
            *protected_plan["inputs"],
            *test_evidence_plan["inputs"],
        )
        if not arguments.no_manifest_file:
            output = (
                arguments.manifest_output
                if arguments.manifest_output is not None
                else root / "local" / "tracked-test-manifest.json"
            )
            if not output.is_absolute():
                output = root / output
            _write_manifest(root, output, manifest)
    except (
        OSError,
        RuntimeError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as exc:
        print(
            json.dumps(
                {
                    "error": str(exc),
                    "schema": "tracked_pytest_manifest_error.v1",
                },
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            manifest,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ),
        flush=True,
    )
    if arguments.manifest_only:
        return 0
    try:
        return _run_isolated_pytest(
            root,
            index_tree=str(manifest["git_index_tree"]),
            tracked=tracked,
            pytest_args=pytest_args,
            execution_timeout_seconds=int(
                manifest["execution_timeout_seconds"]
            ),
            rebuild_runtime_projection=(
                manifest["runtime_projection"]
                == {
                    "authority": "git_index_tree_journal",
                    "mode": "explicit_recovery",
                }
            ),
            transition_plan=(
                manifest["runtime_projection"]
                if manifest["runtime_projection"].get("mode")
                == _HEAD_AUTHORITY_TRANSITION_MODE
                else None
            ),
            runtime_paths=runtime_paths,
            protected_inputs=protected_inputs,
        )
    except (
        OSError,
        RuntimeError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as exc:
        print(
            json.dumps(
                {
                    "error": str(exc),
                    "schema": "tracked_pytest_execution_error.v1",
                },
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
