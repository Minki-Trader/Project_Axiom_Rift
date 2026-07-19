"""Plan the exact sparse repository surface for a focused tracked test."""

from __future__ import annotations

from hashlib import sha256
from pathlib import PurePosixPath
from typing import Callable, Mapping, Sequence


FOCUSED_PROTECTED_DEVELOPMENT = "protected_development"
FOCUSED_TEST_EVIDENCE = "test_evidence"
_INPUT_DIRECTIVE = "# axiom-focused-inputs:"
_DEPENDENCY_DIRECTIVE = "# axiom-focused-dependency:"
_INPUT_ROLES = frozenset(
    {FOCUSED_PROTECTED_DEVELOPMENT, FOCUSED_TEST_EVIDENCE}
)
_AMBIENT_PATHS = (
    ".gitattributes",
    ".gitignore",
    "pyproject.toml",
    "pytest.ini",
    "setup.cfg",
    "tox.ini",
)
_REGULAR_MODES = frozenset({"100644", "100755"})


def directory_identity(content: bytes, *, expected_path: str) -> str:
    """Validate one exact ``git ls-tree -z`` directory result."""

    rows = tuple(row for row in content.split(b"\0") if row)
    if len(rows) != 1:
        raise RuntimeError(f"focused source subtree is unavailable: {expected_path}")
    header, separator, raw_path = rows[0].partition(b"\t")
    fields = header.split()
    try:
        path = raw_path.decode("utf-8")
        tree = fields[2].decode("ascii")
    except (IndexError, UnicodeDecodeError) as exc:
        raise RuntimeError("focused source subtree identity is malformed") from exc
    if (
        not separator
        or len(fields) != 3
        or fields[:2] != [b"040000", b"tree"]
        or path != expected_path
        or len(tree) not in {40, 64}
        or any(character not in "0123456789abcdef" for character in tree)
    ):
        raise RuntimeError("focused source subtree identity is malformed")
    return tree


def tree_inventory(content: bytes) -> dict[str, dict[str, str]]:
    """Parse one recursive ``git ls-tree -z`` result without opening blobs."""

    result: dict[str, dict[str, str]] = {}
    for row in content.split(b"\0"):
        if not row:
            continue
        header, separator, raw_path = row.partition(b"\t")
        fields = header.split()
        if not separator or len(fields) != 3:
            raise RuntimeError("frozen index tree inventory is malformed")
        try:
            path = raw_path.decode("utf-8")
            mode = fields[0].decode("ascii")
            kind = fields[1].decode("ascii")
            blob = fields[2].decode("ascii")
        except (IndexError, UnicodeDecodeError) as exc:
            raise RuntimeError("frozen index tree inventory is malformed") from exc
        relative = PurePosixPath(path)
        if (
            kind != "blob"
            or path in result
            or relative.is_absolute()
            or relative.as_posix() != path
            or any(part in {"", ".", ".."} for part in relative.parts)
            or mode not in {*_REGULAR_MODES, "120000"}
            or not blob
            or any(character not in "0123456789abcdef" for character in blob)
        ):
            raise RuntimeError("frozen index tree inventory is malformed")
        result[path] = {"blob": blob, "mode": mode, "path": path}
    if not result:
        raise RuntimeError("frozen index tree has no entries")
    return result


def bound_entries(
    *,
    inventory: Mapping[str, Mapping[str, str]],
    paths: Sequence[str],
    read_blobs: Callable[[Sequence[str]], Sequence[bytes]],
) -> tuple[dict[str, str], ...]:
    """Open and hash exactly the requested regular blobs."""

    requested = tuple(sorted(paths))
    if not requested or len(requested) != len(set(requested)):
        raise RuntimeError("focused dependency paths are not unique")
    selected: list[Mapping[str, str]] = []
    for path in requested:
        entry = inventory.get(path)
        if entry is None:
            raise RuntimeError(f"frozen dependency is unavailable: {path}")
        if entry.get("mode") not in _REGULAR_MODES:
            raise RuntimeError(f"frozen dependency is not regular: {path}")
        selected.append(entry)
    unique_blobs = tuple(dict.fromkeys(entry["blob"] for entry in selected))
    contents = tuple(read_blobs(unique_blobs))
    if len(contents) != len(unique_blobs):
        raise RuntimeError("frozen dependency blob response is incomplete")
    by_blob = dict(zip(unique_blobs, contents, strict=True))
    return tuple(
        {
            "blob": entry["blob"],
            "mode": entry["mode"],
            "path": entry["path"],
            "sha256": sha256(by_blob[entry["blob"]]).hexdigest(),
        }
        for entry in selected
    )


def selected_test_declarations(
    selected_contents: Mapping[str, bytes],
    *,
    inventory: Mapping[str, Mapping[str, str]],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Read opt-in inputs from selected frozen test bytes only."""

    roles: set[str] = set()
    dependencies: set[str] = set()
    for path in sorted(selected_contents):
        try:
            lines = selected_contents[path].decode("ascii").splitlines()
        except UnicodeDecodeError as exc:
            raise RuntimeError(f"selected tracked test is not ASCII: {path}") from exc
        for line in lines:
            if line.startswith(_INPUT_DIRECTIVE):
                values = tuple(
                    value.strip()
                    for value in line[len(_INPUT_DIRECTIVE) :].split(",")
                )
                if not values or any(value not in _INPUT_ROLES for value in values):
                    raise RuntimeError(
                        "selected tracked test has an invalid focused input "
                        f"declaration: {path}"
                    )
                roles.update(values)
            elif line.startswith(_DEPENDENCY_DIRECTIVE):
                value = line[len(_DEPENDENCY_DIRECTIVE) :].strip()
                relative = PurePosixPath(value)
                entry = inventory.get(value)
                if (
                    not value
                    or not value.isascii()
                    or relative.is_absolute()
                    or relative.as_posix() != value
                    or any(part in {"", ".", ".."} for part in relative.parts)
                    or entry is None
                    or entry.get("mode") not in _REGULAR_MODES
                ):
                    raise RuntimeError(
                        "selected tracked test focused dependency is invalid or "
                        f"unavailable: {value}"
                    )
                dependencies.add(value)
    return tuple(sorted(roles)), tuple(sorted(dependencies))


def dependency_paths(
    *,
    inventory: Mapping[str, Mapping[str, str]],
    selected_files: Sequence[str],
    declared_dependencies: Sequence[str],
) -> tuple[str, ...]:
    """Bind only selected tests, ambient config, and declared extra resources."""

    closure = set(selected_files)
    closure.update(declared_dependencies)
    closure.update(
        path
        for path in _AMBIENT_PATHS
        if inventory.get(path, {}).get("mode") in _REGULAR_MODES
    )
    for selected in selected_files:
        parent = PurePosixPath(selected).parent
        while parent.parts:
            candidate = (parent / "conftest.py").as_posix()
            if inventory.get(candidate, {}).get("mode") in _REGULAR_MODES:
                closure.add(candidate)
            parent = parent.parent
    return tuple(sorted(closure))


def normalized_entries(
    entries: Sequence[Mapping[str, str]],
) -> tuple[dict[str, str], ...]:
    """Validate the exact path/blob set before isolated Git materialization."""

    result: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for raw in entries:
        if not isinstance(raw, Mapping) or set(raw) != {
            "blob",
            "mode",
            "path",
            "sha256",
        }:
            raise RuntimeError("focused snapshot dependency is malformed")
        entry = {key: str(raw[key]) for key in raw}
        path = entry["path"]
        relative = PurePosixPath(path)
        if (
            path in seen_paths
            or not path.isascii()
            or any(ord(character) < 32 for character in path)
            or relative.is_absolute()
            or relative.as_posix() != path
            or any(part in {"", ".", ".."} for part in relative.parts)
            or entry["mode"] not in _REGULAR_MODES
            or len(entry["blob"]) not in {40, 64}
            or any(
                character not in "0123456789abcdef"
                for character in entry["blob"]
            )
            or len(entry["sha256"]) != 64
            or any(
                character not in "0123456789abcdef"
                for character in entry["sha256"]
            )
        ):
            raise RuntimeError("focused snapshot dependency identity is invalid")
        seen_paths.add(path)
        result.append(entry)
    if tuple(entry["path"] for entry in result) != tuple(sorted(seen_paths)):
        raise RuntimeError("focused snapshot dependencies are not canonical")
    return tuple(result)


def normalized_source_tree(value: Mapping[str, object]) -> dict[str, object]:
    """Validate the optional exact ``src`` subtree binding."""

    if value == {"authority": "none", "path_count": 0}:
        return dict(value)
    if set(value) != {"authority", "path", "path_count", "tree"} or (
        value.get("authority") != "git_index_subtree"
        or value.get("path") != "src"
        or type(value.get("path_count")) is not int
        or int(value["path_count"]) < 1
        or type(value.get("tree")) is not str
        or len(str(value["tree"])) not in {40, 64}
        or any(
            character not in "0123456789abcdef"
            for character in str(value["tree"])
        )
    ):
        raise RuntimeError("focused source subtree identity is invalid")
    return dict(value)
