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
from tempfile import TemporaryDirectory
from typing import Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from axiom_rift.core.canonical import canonical_bytes  # noqa: E402


def _git(root: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ("git", *arguments),
        cwd=root,
        check=True,
        capture_output=True,
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
_PROTECTED_INPUT_RULES = (
    ("observed_development", PurePosixPath("data/processed/datasets")),
    ("split_artifact", PurePosixPath("data/processed/coverage_audits")),
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


def _tree_paths(root: Path, index_tree: str) -> tuple[str, ...]:
    return _paths(
        _git(root, "ls-tree", "-r", "-z", "--name-only", index_tree)
    )


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
    prefix = dict(_PROTECTED_INPUT_RULES).get(role)
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
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise RuntimeError(f"cannot hash protected input: {path.name}") from exc
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


def _runtime_discovery_environment() -> dict[str, str]:
    """Expose only host location inputs needed by trusted ``site`` discovery."""

    environment = _sanitized_host_environment()
    for key in ("APPDATA", "LOCALAPPDATA", "USERPROFILE", "HOMEDRIVE", "HOMEPATH"):
        value = os.environ.get(key)
        if value:
            environment[key] = value
    return environment


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
    )
    ordered = (
        completed.stdout.strip(),
        sysconfig.get_path("purelib"),
        sysconfig.get_path("platlib"),
    )
    result: list[str] = []
    for path in ordered:
        if path and path not in result:
            result.append(path)
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
            record_digest: str | None = None
            for item in distribution.files or ():
                relative = PurePosixPath(*Path(str(item)).parts).as_posix()
                if not relative.endswith(".dist-info/RECORD"):
                    continue
                candidate = Path(distribution.locate_file(item))
                if candidate.is_file():
                    record_digest = sha256(candidate.read_bytes()).hexdigest()
                break
            inventory.append(
                {
                    "distribution": normalized,
                    "record_sha256": record_digest,
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
    root: Path, *, pytest_args: Sequence[str]
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
    entries: list[dict[str, str]] = []
    for path in tracked:
        candidate = root / Path(path)
        try:
            candidate.read_bytes()
        except OSError as exc:
            raise RuntimeError(f"tracked test is unavailable: {path}") from exc
        content = _tree_blob(root, index_tree, path)
        blob = _tree_blob_id(root, index_tree, path)
        worktree_blob = (
            _git(root, "hash-object", f"--path={path}", "--", path)
            .decode("ascii")
            .strip()
        )
        if worktree_blob != blob:
            raise RuntimeError(
                "tracked test worktree bytes differ from the Git index blob: " + path
            )
        entries.append(
            {"blob": blob, "path": path, "sha256": sha256(content).hexdigest()}
        )
    python_runtime, runtime_paths = _python_runtime()
    protected_inputs = _protected_development_input_plan(
        root, index_tree=index_tree, tracked_paths=tracked_paths
    )
    body: dict[str, object] = {
        "execution_mode": "isolated_git_index_tree",
        "excluded_untracked_test_count": len(untracked),
        "excluded_untracked_tests": list(untracked),
        "git_head": head,
        "git_index_tree": index_tree,
        "protected_development_inputs": protected_inputs,
        "pytest_args": list(pytest_args),
        "python_runtime": python_runtime,
        "runtime_projection": _runtime_projection_plan(tracked_paths),
        "sandbox_origin_policy": "detached_no_remote_no_push",
        "schema": "tracked_pytest_manifest.v2",
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
        tracked,
        runtime_paths,
    )


def _isolated_environment(
    sandbox: Path, *, runtime_paths: Sequence[str]
) -> dict[str, str]:
    environment = _sanitized_host_environment()
    home = sandbox / "local" / "isolated-home"
    temporary = sandbox / "local" / "isolated-tmp"
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
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    # The exact index-tree root is required for intentional ``tests.*``
    # imports.  The sandbox contains no source-worktree untracked files.
    python_paths: list[str | Path] = [
        sandbox / "src",
        sandbox,
        *runtime_paths,
    ]
    environment["PYTHONPATH"] = os.pathsep.join(str(path) for path in python_paths)
    environment["PYTHONSAFEPATH"] = "1"
    return environment


def _rebuild_runtime_projection(
    sandbox: Path, *, runtime_paths: Sequence[str]
) -> None:
    """Rebuild disposable SQLite state from the checked-out Journal authority."""

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
            sandbox, runtime_paths=runtime_paths
        ),
        check=False,
        capture_output=True,
    )
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
    if (
        subprocess.run(
            ("git", "diff", "--quiet", "--"),
            cwd=sandbox,
            check=False,
            capture_output=True,
        ).returncode
        != 0
    ):
        raise RuntimeError(
            "isolated Journal projection rebuild changed tracked authority bytes"
        )


def _validated_protected_entry(value: object) -> dict[str, object]:
    required = {"path", "role", "sha256", "size"}
    if not isinstance(value, Mapping) or set(value) != required:
        raise RuntimeError("protected input manifest entry is malformed")
    role = value.get("role")
    if type(role) is not str or role not in dict(_PROTECTED_INPUT_RULES):
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
    current = sandbox
    for part in relative.parent.parts:
        current = current / part
        if current.exists():
            if _is_link_like(current) or not current.is_dir():
                raise RuntimeError(
                    "protected input sandbox destination is link-like or non-directory"
                )
        else:
            current.mkdir()
    destination = sandbox.joinpath(*relative.parts)
    if destination.exists() or _is_link_like(destination):
        raise RuntimeError("protected input sandbox destination already exists")
    return destination


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
    try:
        with source.open("rb") as source_handle, destination.open("xb") as target:
            before = os.fstat(source_handle.fileno())
            while True:
                chunk = source_handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                copied += len(chunk)
                target.write(chunk)
            target.flush()
            after = os.fstat(source_handle.fileno())
        source_identity = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        )
        if source_identity != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise RuntimeError("protected input changed during materialization")
        if digest.hexdigest() != entry["sha256"] or copied != entry["size"]:
            raise RuntimeError("protected input changed before materialization")
        destination_digest, destination_size = _hash_file(destination)
        if (
            destination_digest != entry["sha256"]
            or destination_size != entry["size"]
        ):
            raise RuntimeError("materialized protected input identity differs")
        destination.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    except Exception:
        try:
            destination.unlink()
        except FileNotFoundError:
            pass
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
    if validated and observed_roles != expected_roles:
        raise RuntimeError(
            "protected input manifest must contain the exact approved role set"
        )
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
        mode = destination.stat().st_mode
        if mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
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
            destination.chmod(stat.S_IRUSR | stat.S_IWUSR)
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
    if _git(sandbox, "remote").strip():
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
    subprocess.run(
        (
            "git",
            "clone",
            "--shared",
            "--no-checkout",
            "--quiet",
            str(root),
            str(sandbox),
        ),
        cwd=root,
        check=True,
        capture_output=True,
    )
    _git(sandbox, "read-tree", index_tree)
    _git(sandbox, "checkout-index", "--all", "--force")
    observed_tree = _git(sandbox, "write-tree").decode("ascii").strip()
    if observed_tree != index_tree:
        raise RuntimeError("isolated pytest index tree differs")

    shared_git = sandbox / ".git"
    if (
        _is_link_like(shared_git)
        or not shared_git.is_dir()
        or shared_git.resolve(strict=True).parent != sandbox
    ):
        raise RuntimeError("shared Git metadata is not a confined directory")
    shutil.rmtree(shared_git)
    _git(sandbox, "init", "--quiet", "--initial-branch=isolated")
    _git(sandbox, "config", "user.email", "isolated-test@example.invalid")
    _git(sandbox, "config", "user.name", "Axiom Isolated Test")
    _git(sandbox, "add", "--force", "--all")
    sealed_tree = _git(sandbox, "write-tree").decode("ascii").strip()
    if sealed_tree != index_tree:
        raise RuntimeError("independent Git snapshot tree differs")
    _git(
        sandbox,
        "-c",
        "core.hooksPath=.git/disabled-hooks",
        "commit",
        "--quiet",
        "--no-gpg-sign",
        "-m",
        "Isolated tracked-test snapshot",
    )
    committed_tree = (
        _git(sandbox, "rev-parse", "HEAD^{tree}").decode("ascii").strip()
    )
    if committed_tree != index_tree:
        raise RuntimeError("independent Git commit tree differs")
    _git(sandbox, "config", "core.hooksPath", ".githooks")
    _verify_independent_git_metadata(sandbox, root)


def _run_isolated_pytest(
    root: Path,
    *,
    index_tree: str,
    tracked: Sequence[str],
    pytest_args: Sequence[str],
    rebuild_runtime_projection: bool,
    runtime_paths: Sequence[str],
    protected_inputs: Sequence[object] = (),
) -> int:
    with TemporaryDirectory(prefix="tracked-pytest-") as temporary:
        sandbox = Path(temporary).resolve()
        if root == sandbox or root in sandbox.parents:
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
            if rebuild_runtime_projection:
                _rebuild_runtime_projection(
                    sandbox, runtime_paths=runtime_paths
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
                    sandbox, runtime_paths=runtime_paths
                ),
                check=False,
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
        if execution_error is not None:
            raise execution_error
        if completed is None:
            raise RuntimeError("isolated pytest did not produce a completion")
        return completed.returncode


def _write_manifest(root: Path, output: Path, manifest: dict[str, object]) -> None:
    local = (root / "local").resolve()
    destination = output.resolve()
    if destination != local and local not in destination.parents:
        raise RuntimeError("manifest output must remain under local/")
    content = canonical_bytes(manifest) + b"\n"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    try:
        temporary.write_bytes(content)
        temporary.replace(destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


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
            root, pytest_args=pytest_args
        )
        protected_plan = manifest.get("protected_development_inputs")
        if not isinstance(protected_plan, dict) or not isinstance(
            protected_plan.get("inputs"), list
        ):
            raise RuntimeError("protected development input plan is malformed")
        protected_inputs = tuple(protected_plan["inputs"])
        if not arguments.no_manifest_file:
            output = (
                arguments.manifest_output
                if arguments.manifest_output is not None
                else root / "local" / "tracked-test-manifest.json"
            )
            if not output.is_absolute():
                output = root / output
            _write_manifest(root, output, manifest)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
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
            rebuild_runtime_projection=(
                manifest["runtime_projection"]
                == {
                    "authority": "git_index_tree_journal",
                    "mode": "explicit_recovery",
                }
            ),
            runtime_paths=runtime_paths,
            protected_inputs=protected_inputs,
        )
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
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
