"""Git delivery guard for legacy and segmented Study-close checkpoints."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import subprocess
from typing import Any, Mapping, Sequence

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.operations.study_close_checkpoint import (
    CHECKPOINT_PATH,
    CHECKPOINT_SCHEMA,
    EMPTY_CLOSE_CHAIN_DIGEST,
    CheckpointPathBlob,
    HistoricalKpiBackfillProof,
    JournalDeliveryCursor,
    LEGACY_CHECKPOINT_SCHEMA,
    StudyCloseCheckpointError,
    StudyCloseDeliveryCheckpoint,
    advance_close_chain,
    validate_checkpoint_transition,
    validate_no_close_suffix,
)
from axiom_rift.operations.study_close_backfill import (
    HistoricalBackfillProofError,
    backfill_trailer_commits,
    historical_backfill_event,
    historical_backfill_sources,
)
from axiom_rift.operations.study_close_backfill_git import (
    BackfillCommitMetadata,
    BackfillCommitSnapshot,
    authenticate_git_backfill_proof,
    build_git_authenticated_backfill_proof,
)
from axiom_rift.operations.study_close_delivery import (
    StudyCloseCheckpointPlan,
    StudyCloseDeliveryPolicyError,
    StudyCloseGuardCapability,
    canonical_milestone_paths,
    exact_staging_paths,
    project_checkpoint_maintenance,
    project_checkpoint_v2_upgrade,
    prospective_closes,
    validate_delivery_checkpoint,
)
from axiom_rift.storage.journal import (
    DurableJournal,
    JOURNAL_DIRECTORY_RELATIVE_PATH,
    JOURNAL_MANIFEST_RELATIVE_PATH,
    JournalIntegrityError,
    JournalSnapshot,
    LEGACY_JOURNAL_RELATIVE_PATH,
    read_journal_snapshot,
)
from axiom_rift.storage.study_kpi import StudyKpiProjectionRow, render_study_kpi


CONTROL_PATH = "state/control.json"
KPI_PATH = "records/STUDY_KPI.md"
REPAIR_MANIFEST_PATH = "records/STUDY_CLOSE_DELIVERY_REPAIR.json"
BASE_REQUIRED_PATHS = (CONTROL_PATH, KPI_PATH)
# Kept as the exact legacy checkpoint surface for compatibility callers.
REQUIRED_PATHS = (CONTROL_PATH, LEGACY_JOURNAL_RELATIVE_PATH, KPI_PATH)
COMMIT_MSG_HOOK_PATH = ".githooks/commit-msg"
COMMIT_MSG_HOOK = (
    b'#!/bin/sh\nexec python scripts/validate_study_close_commit.py "$1"\n'
)
_DIGEST = r"[0-9a-f]{64}"
_AUDIT_CACHE_SCHEMA = "study_close_delivery_audit_cache.v1"
_AUDIT_VALIDATOR_VERSION = "study_close_delivery_audit.v2"
_AUDIT_CACHE_RELATIVE_PATH = "local/study-close-delivery-audit.json"
_EMPTY_CLOSE_CHAIN_DIGEST = sha256(b"axiom-study-close-delivery-empty").hexdigest()
_HEX = frozenset("0123456789abcdef")
_CHECKPOINT_INIT_TRAILER = "Axiom-Study-Close-Checkpoint"
_MAX_TRACKED_SUFFIX_BYTES = 2 * DurableJournal.MAX_SEGMENT_BYTES
_MAX_TRACKED_SUFFIX_EVENTS = 2 * DurableJournal.MAX_SEGMENT_EVENTS
_ORIGIN_ATTEMPT_RELATIVE_PATH = "local/study-close-origin-attempt.json"
_ORIGIN_ATTEMPT_SCHEMA = "study_close_origin_attempt.v1"
_ORIGIN_REMOTE = "origin"
_ORIGIN_REMOTE_REF = "origin/main"
_ORIGIN_PUSH_TIMEOUT_SECONDS = 30


class StudyCloseDeliveryError(RuntimeError):
    """A Study-close Git checkpoint is absent or malformed."""


class _AuditCacheStale(RuntimeError):
    """The rebuildable local audit cache no longer matches repository bytes."""


@dataclass(frozen=True, slots=True)
class _JournalCursor:
    active_path: str
    active_start_offset: int
    layout_digest: str
    sequence: int
    event_id: str | None
    previous_event_id: str | None
    event_offset: int | None
    event_bytes: int
    next_offset: int
    prefix_digest: str

    def payload(self) -> dict[str, Any]:
        return {
            "active_path": self.active_path,
            "active_start_offset": self.active_start_offset,
            "event_bytes": self.event_bytes,
            "event_id": self.event_id,
            "event_offset": self.event_offset,
            "layout_digest": self.layout_digest,
            "next_offset": self.next_offset,
            "prefix_digest": self.prefix_digest,
            "previous_event_id": self.previous_event_id,
            "sequence": self.sequence,
        }
def _require_git_repository(
    root: Path,
    *,
    capability: StudyCloseGuardCapability | None = None,
) -> bool:
    if capability is StudyCloseGuardCapability.ISOLATED_ENGINEERING_FIXTURE:
        try:
            _git(root, "rev-parse", "--show-toplevel")
        except (OSError, subprocess.CalledProcessError):
            return False
        raise StudyCloseDeliveryError(
            "engineering-fixture delivery capability cannot target a Git repository"
        )
    if capability is not None:
        raise StudyCloseDeliveryError("Study-close guard capability is invalid")
    _verified_git_repository_root(str(root))
    return True


@lru_cache(maxsize=16)
def _verified_git_repository_root(root_value: str) -> None:
    root = Path(root_value)
    try:
        top = Path(str(_git(root, "rev-parse", "--show-toplevel"))).resolve()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise StudyCloseDeliveryError(
            "real scientific delivery requires a verifiable Git repository"
        ) from exc
    if top != root:
        raise StudyCloseDeliveryError(
            "Study-close delivery root differs from the Git repository root"
        )


def require_local_main(repository_root: str | Path) -> None:
    """Require the delivery operation to run on the checked-out main branch."""

    root = Path(repository_root).resolve()
    _require_git_repository(root)
    try:
        branch = str(_git(root, "symbolic-ref", "--short", "HEAD"))
    except (OSError, subprocess.CalledProcessError) as exc:
        raise StudyCloseDeliveryError(
            "Study-close delivery cannot verify the local main branch"
        ) from exc
    if branch != "main":
        raise StudyCloseDeliveryError(
            "Study-close delivery must run on checked-out local main"
        )
    try:
        head = str(_git(root, "rev-parse", "HEAD"))
        main = str(_git(root, "rev-parse", "main"))
    except (OSError, subprocess.CalledProcessError) as exc:
        raise StudyCloseDeliveryError(
            "Study-close delivery cannot verify the local main branch"
        ) from exc
    if head != main:
        raise StudyCloseDeliveryError(
            "Study-close delivery must run on checked-out local main"
        )


def require_study_close_guard_ready(
    repository_root: str | Path,
    *,
    capability: StudyCloseGuardCapability | None = None,
) -> None:
    """Fail closed unless the tracked Study-close commit trigger is active."""

    root = Path(repository_root).resolve()
    if not _require_git_repository(root, capability=capability):
        return
    try:
        hooks_path = str(_git(root, "config", "--get", "core.hooksPath"))
    except subprocess.CalledProcessError:
        hooks_path = ""
    if hooks_path != ".githooks":
        raise StudyCloseDeliveryError(
            "Study-close commit guard requires core.hooksPath=.githooks"
        )
    hook = root / COMMIT_MSG_HOOK_PATH
    try:
        hook_bytes = hook.read_bytes().replace(b"\r\n", b"\n")
    except OSError as exc:
        raise StudyCloseDeliveryError(
            "tracked Study-close commit-msg hook is unavailable"
        ) from exc
    if hook_bytes != COMMIT_MSG_HOOK:
        raise StudyCloseDeliveryError("tracked Study-close commit-msg hook differs")
    staged_entry = str(_git(root, "ls-files", "--stage", "--", COMMIT_MSG_HOOK_PATH))
    if not staged_entry.startswith("100755 "):
        raise StudyCloseDeliveryError(
            "Study-close commit-msg hook is not tracked executable"
        )


def _git(root: Path, *arguments: str, binary: bool = False) -> bytes | str:
    result = subprocess.run(
        ("git", *arguments), cwd=root, check=True, capture_output=True
    )
    return result.stdout if binary else result.stdout.decode("ascii").strip()


@dataclass(frozen=True, slots=True)
class _OriginGitResult:
    returncode: int
    stdout: bytes
    stderr: bytes


def _run_origin_git(root: Path, *arguments: str) -> _OriginGitResult:
    environment = os.environ.copy()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    environment["GCM_INTERACTIVE"] = "Never"
    try:
        completed = subprocess.run(
            ("git", *arguments),
            cwd=root,
            check=False,
            capture_output=True,
            timeout=_ORIGIN_PUSH_TIMEOUT_SECONDS,
            env=environment,
        )
        return _OriginGitResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, bytes) else b""
        stderr = exc.stderr if isinstance(exc.stderr, bytes) else b""
        return _OriginGitResult(
            returncode=124,
            stdout=stdout,
            stderr=stderr + b"bounded Git delivery timeout",
        )


def _ancestor(root: Path, commit: str, reference: str) -> bool:
    return (
        subprocess.run(
            ("git", "merge-base", "--is-ancestor", commit, reference),
            cwd=root,
            check=False,
            capture_output=True,
        ).returncode
        == 0
    )


def _origin_attempt_path(root: Path) -> Path:
    return root / _ORIGIN_ATTEMPT_RELATIVE_PATH


def _origin_ref_commit(root: Path) -> str | None:
    result = _run_origin_git(root, "rev-parse", "--verify", _ORIGIN_REMOTE_REF)
    if result.returncode != 0:
        return None
    try:
        value = result.stdout.decode("ascii").strip()
    except UnicodeDecodeError:
        return None
    if len(value) not in {40, 64} or any(
        character not in "0123456789abcdef" for character in value
    ):
        return None
    return value


def _origin_attempt_body(
    *,
    checkpoint_digest: str,
    target_commit: str,
    attempt_main_head: str,
    fetch: _OriginGitResult,
    push: _OriginGitResult,
    observed_remote_before: str | None,
    observed_remote_after: str | None,
    outcome: str,
) -> dict[str, Any]:
    return {
        "attempt_main_head": attempt_main_head,
        "checkpoint_digest": checkpoint_digest,
        "fetch_returncode": fetch.returncode,
        "fetch_stderr_sha256": sha256(fetch.stderr).hexdigest(),
        "fetch_stdout_sha256": sha256(fetch.stdout).hexdigest(),
        "observed_remote_after": observed_remote_after,
        "observed_remote_before": observed_remote_before,
        "outcome": outcome,
        "push_returncode": push.returncode,
        "push_stderr_sha256": sha256(push.stderr).hexdigest(),
        "push_stdout_sha256": sha256(push.stdout).hexdigest(),
        "remote_ref": _ORIGIN_REMOTE_REF,
        "schema": _ORIGIN_ATTEMPT_SCHEMA,
        "target_commit": target_commit,
    }


def _write_origin_attempt(root: Path, body: Mapping[str, Any]) -> None:
    payload = {
        **body,
        "receipt_sha256": sha256(canonical_bytes(body)).hexdigest(),
    }
    path = _origin_attempt_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    content = canonical_bytes(payload) + b"\n"
    try:
        with temporary.open("wb", buffering=0) as handle:
            if handle.write(content) != len(content):
                raise OSError("short origin-attempt receipt write")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _matching_origin_attempt(
    root: Path,
    *,
    checkpoint_digest: str,
    target_commit: str,
    attempt_main_head: str,
) -> bool:
    try:
        content = _origin_attempt_path(root).read_bytes()
        if not content.endswith(b"\n") or content.count(b"\n") != 1:
            return False
        value = parse_canonical(content[:-1])
    except (OSError, TypeError, ValueError):
        return False
    expected = {
        "attempt_main_head",
        "checkpoint_digest",
        "fetch_returncode",
        "fetch_stderr_sha256",
        "fetch_stdout_sha256",
        "observed_remote_after",
        "observed_remote_before",
        "outcome",
        "push_returncode",
        "push_stderr_sha256",
        "push_stdout_sha256",
        "receipt_sha256",
        "remote_ref",
        "schema",
        "target_commit",
    }
    if not isinstance(value, dict) or set(value) != expected:
        return False
    receipt = value.pop("receipt_sha256")
    if (
        value.get("schema") != _ORIGIN_ATTEMPT_SCHEMA
        or value.get("remote_ref") != _ORIGIN_REMOTE_REF
        or value.get("checkpoint_digest") != checkpoint_digest
        or value.get("target_commit") != target_commit
        or value.get("attempt_main_head") != attempt_main_head
        or value.get("outcome") not in {"delivered", "delivery_debt"}
        or type(value.get("push_returncode")) is not int
        or type(value.get("fetch_returncode")) is not int
    ):
        return False
    for key in (
        "fetch_stderr_sha256",
        "fetch_stdout_sha256",
        "push_stderr_sha256",
        "push_stdout_sha256",
    ):
        try:
            _digest(value.get(key), f"origin receipt {key}")
        except _AuditCacheStale:
            return False
    return (
        type(receipt) is str
        and receipt == sha256(canonical_bytes(value)).hexdigest()
    )


@lru_cache(maxsize=32)
def _ensure_origin_delivery_observed(
    root_value: str,
    main_head: str,
    checkpoint_digest: str,
    target_commit: str,
) -> None:
    """Refresh origin and make one bounded non-force push attempt per main head."""

    root = Path(root_value)
    if _matching_origin_attempt(
        root,
        checkpoint_digest=checkpoint_digest,
        target_commit=target_commit,
        attempt_main_head=main_head,
    ):
        return
    fetch = _run_origin_git(
        root,
        "fetch",
        "--no-tags",
        _ORIGIN_REMOTE,
        "main:refs/remotes/origin/main",
    )
    observed_before = _origin_ref_commit(root)
    if (
        fetch.returncode == 0
        and observed_before is not None
        and _ancestor(root, target_commit, _ORIGIN_REMOTE_REF)
    ):
        observed = _OriginGitResult(returncode=0, stdout=b"", stderr=b"")
        try:
            _write_origin_attempt(
                root,
                _origin_attempt_body(
                    checkpoint_digest=checkpoint_digest,
                    target_commit=target_commit,
                    attempt_main_head=main_head,
                    fetch=fetch,
                    push=observed,
                    observed_remote_before=observed_before,
                    observed_remote_after=observed_before,
                    outcome="delivered",
                ),
            )
        except OSError:
            pass
        return
    push = _run_origin_git(
        root,
        "push",
        "--porcelain",
        _ORIGIN_REMOTE,
        "main:main",
    )
    observed_after = _origin_ref_commit(root)
    delivered = (
        push.returncode == 0
        and observed_after is not None
        and _ancestor(root, target_commit, _ORIGIN_REMOTE_REF)
    )
    body = _origin_attempt_body(
        checkpoint_digest=checkpoint_digest,
        target_commit=target_commit,
        attempt_main_head=main_head,
        fetch=fetch,
        push=push,
        observed_remote_before=observed_before,
        observed_remote_after=observed_after,
        outcome="delivered" if delivered else "delivery_debt",
    )
    try:
        _write_origin_attempt(root, body)
    except OSError:
        # The bounded attempt already occurred. A later process safely retries
        # if the non-authoritative local receipt could not be retained.
        pass


def _snapshot(root: Path, commit: str, path: str) -> bytes:
    value = _git(root, "show", f"{commit}:{path}", binary=True)
    assert isinstance(value, bytes)
    return value


def _optional_git_file(root: Path, specifier: str, path: str) -> bytes | None:
    try:
        value = _git(root, "show", f"{specifier}{path}", binary=True)
    except subprocess.CalledProcessError:
        return None
    assert isinstance(value, bytes)
    return value


def _optional_worktree_file(root: Path, path: str) -> bytes | None:
    candidate = root / Path(path)
    try:
        return candidate.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise StudyCloseDeliveryError(
            f"checkpoint authority input is unavailable: {path}"
        ) from exc


def _journal_paths_from_git(root: Path, *arguments: str) -> tuple[str, ...]:
    try:
        output = str(_git(root, *arguments))
    except subprocess.CalledProcessError:
        return ()
    return tuple(path for path in output.splitlines() if path)


def _worktree_journal_paths(root: Path) -> tuple[str, ...]:
    paths: list[str] = []
    legacy = root / LEGACY_JOURNAL_RELATIVE_PATH
    if legacy.is_file():
        paths.append(LEGACY_JOURNAL_RELATIVE_PATH)
    directory = root / JOURNAL_DIRECTORY_RELATIVE_PATH
    if directory.is_dir():
        paths.extend(
            candidate.relative_to(root).as_posix()
            for candidate in directory.iterdir()
            if candidate.is_file() and not candidate.name.startswith(".")
        )
    return tuple(sorted(paths))


def _require_clean_checkpoint_authority_inputs(
    root: Path,
    *,
    allow_staged_checkpoint: bool,
) -> None:
    """Bind full-maintenance input bytes to main, index, and worktree."""

    fixed = (CONTROL_PATH, KPI_PATH, REPAIR_MANIFEST_PATH)
    main_journal = _journal_paths_from_git(
        root,
        "ls-tree",
        "-r",
        "--name-only",
        "main",
        "--",
        LEGACY_JOURNAL_RELATIVE_PATH,
        JOURNAL_DIRECTORY_RELATIVE_PATH,
    )
    index_journal = _journal_paths_from_git(
        root,
        "ls-files",
        "--cached",
        "--",
        LEGACY_JOURNAL_RELATIVE_PATH,
        JOURNAL_DIRECTORY_RELATIVE_PATH,
    )
    worktree_journal = _worktree_journal_paths(root)
    if not (set(main_journal) == set(index_journal) == set(worktree_journal)):
        raise StudyCloseDeliveryError(
            "checkpoint full maintenance requires identical main, index, and "
            "worktree Journal path sets"
        )
    for path in (*fixed, *sorted(set(main_journal))):
        main_content = _optional_git_file(root, "main:", path)
        index_content = _optional_git_file(root, ":", path)
        worktree_content = _optional_worktree_file(root, path)
        if not (main_content == index_content == worktree_content):
            raise StudyCloseDeliveryError(
                "checkpoint full maintenance requires identical main, index, "
                f"and worktree authority bytes: {path}"
            )
    main_checkpoint = _optional_git_file(root, "main:", CHECKPOINT_PATH)
    index_checkpoint = _optional_git_file(root, ":", CHECKPOINT_PATH)
    worktree_checkpoint = _optional_worktree_file(root, CHECKPOINT_PATH)
    if allow_staged_checkpoint:
        if index_checkpoint is None or index_checkpoint != worktree_checkpoint:
            raise StudyCloseDeliveryError(
                "staged checkpoint bytes differ from the worktree"
            )
    elif not (
        main_checkpoint == index_checkpoint == worktree_checkpoint
    ):
        raise StudyCloseDeliveryError(
            "checkpoint full maintenance requires a clean tracked checkpoint"
        )


def _worktree_journal(root: Path) -> JournalSnapshot:
    def load(path: str) -> bytes | None:
        candidate = root / Path(path)
        return candidate.read_bytes() if candidate.is_file() else None

    paths = list(_worktree_journal_paths(root))
    return read_journal_snapshot(load, listed_paths=paths)


def _cache_path(root: Path) -> Path:
    return root / _AUDIT_CACHE_RELATIVE_PATH


def _digest(value: object, label: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in _HEX for character in value)
    ):
        raise _AuditCacheStale(f"{label} is invalid")
    return value


def _commit_identity(value: object, label: str) -> str:
    if (
        type(value) is not str
        or len(value) not in {40, 64}
        or any(character not in _HEX for character in value)
    ):
        raise _AuditCacheStale(f"{label} is invalid")
    return value


def _journal_relative_path(value: object, label: str) -> str:
    if type(value) is not str or "\\" in value:
        raise _AuditCacheStale(f"{label} is invalid")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or tuple(path.parts[:2]) != ("records", "journal")
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != value
    ):
        raise _AuditCacheStale(f"{label} escapes the Journal directory")
    return value


def _journal_layout(
    root: Path,
) -> tuple[str, str, int, Mapping[str, Any] | None]:
    legacy = root / LEGACY_JOURNAL_RELATIVE_PATH
    manifest_path = root / JOURNAL_MANIFEST_RELATIVE_PATH
    if legacy.is_file() and manifest_path.is_file():
        raise _AuditCacheStale("legacy and segmented Journal layouts overlap")
    if legacy.is_file():
        return (
            sha256(b"study-close-audit-legacy-layout-v1").hexdigest(),
            LEGACY_JOURNAL_RELATIVE_PATH,
            0,
            None,
        )
    if not manifest_path.is_file():
        return (
            sha256(b"study-close-audit-empty-layout-v1").hexdigest(),
            LEGACY_JOURNAL_RELATIVE_PATH,
            0,
            None,
        )
    try:
        content = manifest_path.read_bytes()
    except OSError as exc:
        raise _AuditCacheStale("Journal manifest is unavailable") from exc
    try:
        value = parse_canonical(content)
    except (TypeError, ValueError) as exc:
        raise _AuditCacheStale("Journal manifest is not canonical") from exc
    if not isinstance(value, dict):
        raise _AuditCacheStale("Journal manifest must be an object")
    active = value.get("active_segment")
    if not isinstance(active, dict):
        raise _AuditCacheStale("active Journal segment declaration is absent")
    active_path = _journal_relative_path(
        active.get("path"), "active Journal segment path"
    )
    if not active_path.endswith(".jsonl"):
        raise _AuditCacheStale("active Journal segment path is invalid")
    start_offset = active.get("start_offset")
    if (
        isinstance(start_offset, bool)
        or not isinstance(start_offset, int)
        or start_offset < 0
    ):
        raise _AuditCacheStale("active Journal segment offset is invalid")
    return sha256(content).hexdigest(), active_path, start_offset, value


def _verify_sealed_segment_bytes(
    root: Path, manifest: Mapping[str, Any] | None
) -> None:
    if manifest is None:
        return
    sealed = manifest.get("sealed_segments")
    if not isinstance(sealed, list):
        raise _AuditCacheStale("sealed Journal segment declarations are invalid")
    try:
        observed = _sealed_journal_verifier(str(root)).verify_sealed_segments(
            expected_manifest_sha256=sha256(canonical_bytes(manifest)).hexdigest()
        )
    except (OSError, JournalIntegrityError) as exc:
        raise _AuditCacheStale("sealed Journal verification failed") from exc
    if observed != len(sealed):
        raise _AuditCacheStale("sealed Journal segment count differs")


@lru_cache(maxsize=2)
def _sealed_journal_verifier(root: str) -> DurableJournal:
    return DurableJournal(Path(root) / LEGACY_JOURNAL_RELATIVE_PATH)


def _cursor_from_snapshot(root: Path, snapshot: JournalSnapshot) -> _JournalCursor:
    layout_digest, active_path, active_start, manifest = _journal_layout(root)
    if snapshot.active_path is not None and snapshot.active_path != active_path:
        raise _AuditCacheStale("validated Journal active path differs")
    try:
        active_content = (root / active_path).read_bytes()
    except OSError:
        if snapshot.layout != "empty":
            raise _AuditCacheStale("active Journal segment is unavailable")
        active_content = b""
    _verify_sealed_segment_bytes(root, manifest)
    if not snapshot.events:
        if active_content:
            raise _AuditCacheStale("empty Journal has active bytes")
        return _JournalCursor(
            active_path=active_path,
            active_start_offset=active_start,
            layout_digest=layout_digest,
            sequence=0,
            event_id=None,
            previous_event_id=None,
            event_offset=None,
            event_bytes=0,
            next_offset=active_start,
            prefix_digest=sha256(b"").hexdigest(),
        )
    tail = snapshot.events[-1]
    event_offset = tail["journal_offset"]
    framed = canonical_bytes(tail) + b"\n"
    active_event_offset: int | None = None
    active_event_bytes = 0
    if event_offset >= active_start:
        local_offset = event_offset - active_start
        if active_content[local_offset : local_offset + len(framed)] != framed:
            raise _AuditCacheStale("validated Journal tail bytes differ")
        active_event_offset = event_offset
        active_event_bytes = len(framed)
    else:
        active = manifest.get("active_segment") if manifest is not None else None
        if (
            active_content
            or not isinstance(active, dict)
            or active.get("previous_event_id") != tail["event_id"]
        ):
            raise _AuditCacheStale("active Journal boundary differs")
    next_offset = active_start + len(active_content)
    return _JournalCursor(
        active_path=active_path,
        active_start_offset=active_start,
        layout_digest=layout_digest,
        sequence=tail["sequence"],
        event_id=tail["event_id"],
        previous_event_id=tail["previous_event_id"],
        event_offset=active_event_offset,
        event_bytes=active_event_bytes,
        next_offset=next_offset,
        prefix_digest=sha256(active_content).hexdigest(),
    )


def _cursor_from_mapping(value: object) -> _JournalCursor:
    if not isinstance(value, dict) or set(value) != {
        "active_path",
        "active_start_offset",
        "event_bytes",
        "event_id",
        "event_offset",
        "layout_digest",
        "next_offset",
        "prefix_digest",
        "previous_event_id",
        "sequence",
    }:
        raise _AuditCacheStale("Journal cursor fields differ")
    active_path = value["active_path"]
    if active_path != LEGACY_JOURNAL_RELATIVE_PATH:
        active_path = _journal_relative_path(active_path, "cached active path")
    for key in (
        "active_start_offset",
        "event_bytes",
        "next_offset",
        "sequence",
    ):
        item = value[key]
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise _AuditCacheStale(f"cached {key} is invalid")
    sequence = value["sequence"]
    event_id = value["event_id"]
    previous_event_id = value["previous_event_id"]
    event_offset = value["event_offset"]
    if sequence == 0:
        if (
            event_id is not None
            or previous_event_id is not None
            or event_offset is not None
            or value["event_bytes"] != 0
            or value["next_offset"] != value["active_start_offset"]
        ):
            raise _AuditCacheStale("empty cached Journal cursor differs")
    else:
        _digest(event_id, "cached Journal event id")
        if previous_event_id is not None:
            _digest(previous_event_id, "cached previous Journal event id")
        if event_offset is not None and (
            isinstance(event_offset, bool)
            or not isinstance(event_offset, int)
            or event_offset < 0
        ):
            raise _AuditCacheStale("cached Journal event offset is invalid")
        if (event_offset is None) != (value["event_bytes"] == 0):
            raise _AuditCacheStale("cached Journal event frame differs")
        if event_offset is None:
            if value["next_offset"] != value["active_start_offset"]:
                raise _AuditCacheStale("cached empty active segment differs")
        elif event_offset + value["event_bytes"] != value["next_offset"]:
            raise _AuditCacheStale("cached Journal tail boundary differs")
    if value["next_offset"] < value["active_start_offset"]:
        raise _AuditCacheStale("cached Journal next offset is invalid")
    return _JournalCursor(
        active_path=active_path,
        active_start_offset=value["active_start_offset"],
        layout_digest=_digest(value["layout_digest"], "cached layout digest"),
        sequence=sequence,
        event_id=event_id,
        previous_event_id=previous_event_id,
        event_offset=event_offset,
        event_bytes=value["event_bytes"],
        next_offset=value["next_offset"],
        prefix_digest=_digest(value["prefix_digest"], "cached prefix digest"),
    )


def _scan_journal_suffix(
    root: Path, cursor: _JournalCursor
) -> tuple[list[dict[str, Any]], _JournalCursor]:
    layout_digest, active_path, active_start, manifest = _journal_layout(root)
    if (
        layout_digest != cursor.layout_digest
        or active_path != cursor.active_path
        or active_start != cursor.active_start_offset
    ):
        raise _AuditCacheStale("Journal layout changed")
    _verify_sealed_segment_bytes(root, manifest)
    try:
        content = (root / active_path).read_bytes()
    except FileNotFoundError as exc:
        empty_layout = sha256(b"study-close-audit-empty-layout-v1").hexdigest()
        if cursor.sequence == 0 and cursor.layout_digest == empty_layout:
            content = b""
        else:
            raise _AuditCacheStale("active Journal segment is unavailable") from exc
    except OSError as exc:
        raise _AuditCacheStale("active Journal segment is unavailable") from exc
    local_next = cursor.next_offset - active_start
    if local_next < 0 or local_next > len(content):
        raise _AuditCacheStale("active Journal segment was truncated")
    prefix = content[:local_next]
    if sha256(prefix).hexdigest() != cursor.prefix_digest:
        raise _AuditCacheStale("certified Journal prefix differs")
    if cursor.event_offset is not None:
        local_event = cursor.event_offset - active_start
        framed = prefix[local_event : local_event + cursor.event_bytes]
        if (
            local_event < 0
            or len(framed) != cursor.event_bytes
            or not framed.endswith(b"\n")
        ):
            raise _AuditCacheStale("certified Journal boundary frame differs")
        try:
            boundary = parse_canonical(framed[:-1])
            if not isinstance(boundary, dict):
                raise _AuditCacheStale("certified Journal boundary is not an event")
            observed = DurableJournal.validate_event(
                boundary,
                expected_sequence=cursor.sequence,
                expected_previous=cursor.previous_event_id,
                expected_offset=cursor.event_offset,
            )
        except (TypeError, ValueError, JournalIntegrityError) as exc:
            raise _AuditCacheStale("certified Journal boundary is invalid") from exc
        if observed["event_id"] != cursor.event_id:
            raise _AuditCacheStale("certified Journal boundary identity differs")
    suffix = content[local_next:]
    if suffix and not suffix.endswith(b"\n"):
        raise _AuditCacheStale("Journal suffix has an incomplete tail")
    events: list[dict[str, Any]] = []
    sequence = cursor.sequence + 1
    previous = cursor.event_id
    offset = cursor.next_offset
    event_offset = cursor.event_offset
    event_bytes = cursor.event_bytes
    previous_event_id = cursor.previous_event_id
    for framed in suffix.splitlines(keepends=True):
        if (
            not framed.endswith(b"\n")
            or len(framed) <= 1
            or len(framed) > DurableJournal.MAX_EVENT_BYTES + 1
        ):
            raise _AuditCacheStale("Journal suffix record is incomplete or oversized")
        try:
            value = parse_canonical(framed[:-1])
            if not isinstance(value, dict):
                raise _AuditCacheStale("Journal suffix record is not an event")
            event = DurableJournal.validate_event(
                value,
                expected_sequence=sequence,
                expected_previous=previous,
                expected_offset=offset,
            )
        except (TypeError, ValueError, JournalIntegrityError) as exc:
            raise _AuditCacheStale("Journal suffix record is invalid") from exc
        events.append(event)
        previous_event_id = event["previous_event_id"]
        previous = event["event_id"]
        event_offset = event["journal_offset"]
        event_bytes = len(framed)
        sequence += 1
        offset += len(framed)
    return events, _JournalCursor(
        active_path=active_path,
        active_start_offset=active_start,
        layout_digest=layout_digest,
        sequence=sequence - 1,
        event_id=previous,
        previous_event_id=previous_event_id,
        event_offset=event_offset,
        event_bytes=event_bytes,
        next_offset=offset,
        prefix_digest=sha256(content).hexdigest(),
    )


def _read_file_suffix(path: Path, offset: int) -> bytes:
    """Read bytes at and after one already-authenticated file boundary."""

    with path.open("rb") as handle:
        handle.seek(offset)
        return handle.read()


def _tracked_segment_ranges(
    root: Path,
) -> tuple[tuple[str, int, int, str | None], ...]:
    """Return current virtual Journal ranges without reading old segment bytes."""

    _layout, active_path, active_start, manifest = _journal_layout(root)
    if manifest is None:
        path = root / LEGACY_JOURNAL_RELATIVE_PATH
        size = path.stat().st_size if path.is_file() else 0
        return ((LEGACY_JOURNAL_RELATIVE_PATH, 0, size, None),)
    sealed = manifest.get("sealed_segments")
    if not isinstance(sealed, list):
        raise _AuditCacheStale("sealed Journal declarations are invalid")
    result: list[tuple[str, int, int, str | None]] = []
    expected_start = 0
    for ordinal, descriptor in enumerate(sealed):
        if not isinstance(descriptor, dict):
            raise _AuditCacheStale("sealed Journal descriptor is invalid")
        path = _journal_relative_path(
            descriptor.get("path"), f"sealed Journal path {ordinal}"
        )
        start = descriptor.get("start_offset")
        length = descriptor.get("byte_length")
        digest = descriptor.get("sha256")
        if (
            isinstance(start, bool)
            or not isinstance(start, int)
            or start != expected_start
            or isinstance(length, bool)
            or not isinstance(length, int)
            or length <= 0
        ):
            raise _AuditCacheStale("sealed Journal range is invalid")
        result.append((path, start, length, _digest(digest, "sealed segment hash")))
        expected_start += length
    if active_start != expected_start:
        raise _AuditCacheStale("active Journal range is not contiguous")
    active = root / active_path
    try:
        active_size = active.stat().st_size
    except OSError as exc:
        raise _AuditCacheStale("active Journal segment is unavailable") from exc
    result.append((active_path, active_start, active_size, None))
    return tuple(result)


def _scan_tracked_journal_suffix(
    root: Path, cursor: JournalDeliveryCursor
) -> tuple[list[dict[str, Any]], JournalDeliveryCursor]:
    """Verify one tracked boundary and parse only the bounded later Journal bytes."""

    verifier = DurableJournal(root / LEGACY_JOURNAL_RELATIVE_PATH)
    if cursor.sequence:
        assert cursor.event_offset is not None and cursor.event_id is not None
        try:
            boundary = verifier.read_event_at(
                offset=cursor.event_offset,
                expected_sequence=cursor.sequence,
                expected_event_id=cursor.event_id,
            )
        except (OSError, JournalIntegrityError) as exc:
            raise _AuditCacheStale("tracked Journal boundary is invalid") from exc
        framed = canonical_bytes(boundary) + b"\n"
        if (
            boundary.get("previous_event_id") != cursor.previous_event_id
            or len(framed) != cursor.event_bytes
            or sha256(framed).hexdigest() != cursor.boundary_sha256
            or boundary.get("journal_offset") != cursor.event_offset
        ):
            raise _AuditCacheStale("tracked Journal boundary differs")

    try:
        ranges = _tracked_segment_ranges(root)
    except (OSError, _AuditCacheStale) as exc:
        raise _AuditCacheStale("current Journal layout is invalid") from exc
    journal_end = ranges[-1][1] + ranges[-1][2]
    if cursor.next_offset > journal_end:
        raise _AuditCacheStale("Journal was truncated before tracked high-water")

    pieces: list[tuple[str, int, bytes]] = []
    total_bytes = 0
    next_offset = cursor.next_offset
    for path, start, length, sealed_digest in ranges:
        end = start + length
        if end <= next_offset:
            continue
        if next_offset < start:
            raise _AuditCacheStale("Journal suffix has a byte-range gap")
        local = next_offset - start
        source = root / path
        if sealed_digest is None:
            try:
                content = _read_file_suffix(source, local)
            except OSError as exc:
                raise _AuditCacheStale("Journal suffix is unavailable") from exc
        else:
            # A newly sealed segment is bounded by the Journal segment limit.
            # Hash it once because its authenticated descriptor covers the whole
            # immutable file; old segments before the high-water are not read.
            try:
                whole = source.read_bytes()
            except OSError as exc:
                raise _AuditCacheStale("sealed Journal suffix is unavailable") from exc
            if len(whole) != length or sha256(whole).hexdigest() != sealed_digest:
                raise _AuditCacheStale("sealed Journal suffix hash differs")
            content = whole[local:]
        if len(content) != end - next_offset:
            raise _AuditCacheStale("Journal suffix length differs")
        total_bytes += len(content)
        if total_bytes > _MAX_TRACKED_SUFFIX_BYTES:
            raise _AuditCacheStale(
                "Journal suffix exceeds the tracked maintenance bound; run the "
                "explicit no-close checkpoint maintenance action"
            )
        pieces.append((path, next_offset, content))
        next_offset = end

    events: list[dict[str, Any]] = []
    sequence = cursor.sequence + 1
    previous = cursor.event_id
    last_path = cursor.journal_path
    for path, start, content in pieces:
        offset = start
        if content and not content.endswith(b"\n"):
            raise _AuditCacheStale("Journal suffix has an incomplete tail")
        for framed in content.splitlines(keepends=True):
            if (
                not framed.endswith(b"\n")
                or len(framed) <= 1
                or len(framed) > DurableJournal.MAX_EVENT_BYTES + 1
            ):
                raise _AuditCacheStale(
                    "Journal suffix record is incomplete or oversized"
                )
            try:
                value = parse_canonical(framed[:-1])
                if not isinstance(value, dict):
                    raise _AuditCacheStale("Journal suffix record is not an event")
                event = DurableJournal.validate_event(
                    value,
                    expected_sequence=sequence,
                    expected_previous=previous,
                    expected_offset=offset,
                )
            except (TypeError, ValueError, JournalIntegrityError) as exc:
                raise _AuditCacheStale("Journal suffix record is invalid") from exc
            events.append(event)
            if len(events) > _MAX_TRACKED_SUFFIX_EVENTS:
                raise _AuditCacheStale(
                    "Journal suffix exceeds the tracked event bound; run the "
                    "explicit no-close checkpoint maintenance action"
                )
            previous = event["event_id"]
            sequence += 1
            offset += len(framed)
            last_path = path

    if not events:
        return events, cursor
    return events, JournalDeliveryCursor.from_events(
        events, journal_path=last_path
    )


def _repair_manifest_digest(root: Path) -> str | None:
    repair_path = root / REPAIR_MANIFEST_PATH
    return (
        sha256(repair_path.read_bytes()).hexdigest()
        if repair_path.is_file()
        else None
    )


def _repair_manifest_digest_from_index(root: Path) -> str | None:
    content = _optional_git_file(
        root, ":", REPAIR_MANIFEST_PATH
    )
    return None if content is None else sha256(content).hexdigest()


def _checkpoint_projection(
    *,
    journal: JournalSnapshot,
    control_content: bytes,
    kpi_content: bytes,
) -> tuple[list[dict[str, Any]], JournalDeliveryCursor]:
    events = _events(journal)
    try:
        control = json.loads(control_content)
    except (TypeError, ValueError) as exc:
        raise StudyCloseDeliveryError("checkpoint control is invalid") from exc
    if not isinstance(control, dict):
        raise StudyCloseDeliveryError("checkpoint control must be an object")
    sequence = 0 if not events else events[-1]["sequence"]
    event_id = None if not events else events[-1]["event_id"]
    try:
        observed_sequence = control["heads"]["journal"]["sequence"]
        observed_event_id = control["heads"]["journal"]["event_id"]
        revision = control["revision"]
    except (KeyError, TypeError) as exc:
        raise StudyCloseDeliveryError("checkpoint control head is absent") from exc
    if (
        observed_sequence != sequence
        or observed_event_id != event_id
        or revision != sequence
    ):
        raise StudyCloseDeliveryError("checkpoint control and Journal heads differ")
    if kpi_content != render_projection(events):
        raise StudyCloseDeliveryError("checkpoint KPI projection differs")
    return events, JournalDeliveryCursor.from_events(
        events, journal_path=journal.active_path
    )


def _historical_backfill_event(
    events: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    try:
        return historical_backfill_event(events)
    except HistoricalBackfillProofError as exc:
        raise StudyCloseDeliveryError(str(exc)) from exc


def _historical_backfill_sources(
    events: Sequence[Mapping[str, Any]],
    event: Mapping[str, Any],
):
    try:
        return historical_backfill_sources(events, event)
    except HistoricalBackfillProofError as exc:
        raise StudyCloseDeliveryError(str(exc)) from exc


def _backfill_trailer_commits(
    root: Path, reference: str = "main"
) -> dict[tuple[str, int], list[str]]:
    output = str(_git(root, "log", reference, "--format=%H%x1f%B%x1e"))
    return backfill_trailer_commits(output)


def _commit_parent_tree_message(root: Path, commit: str) -> tuple[str, str, str]:
    output = str(
        _git(root, "show", "-s", "--format=%P%x1f%T%x1f%B", commit)
    )
    parts = output.split("\x1f", 2)
    if len(parts) != 3 or len(parts[0].split()) != 1:
        raise StudyCloseDeliveryError(
            "historical KPI backfill commit metadata is malformed"
        )
    return parts[0].strip(), parts[1].strip(), parts[2]


def _build_historical_backfill_proof(
    root: Path,
    events: Sequence[Mapping[str, Any]],
    *,
    ancestry_anchor: str,
) -> HistoricalKpiBackfillProof | None:
    event = _historical_backfill_event(events)
    if event is None:
        return None
    commits = _backfill_trailer_commits(root)
    matches = commits.get((event["event_id"], event["sequence"]), [])
    if len(matches) != 1:
        raise StudyCloseDeliveryError(
            "historical KPI backfill lacks one authenticated commit"
        )
    commit = matches[0]
    parent, tree, message = _commit_parent_tree_message(root, commit)
    try:
        journal = _commit_journal(root, commit, validate_events=True)
        commit_events, _cursor = _checkpoint_projection(
            journal=journal,
            control_content=_snapshot(root, commit, CONTROL_PATH),
            kpi_content=_snapshot(root, commit, KPI_PATH),
        )
        parent_journal = _parent_journal(root, commit)
    except (OSError, subprocess.CalledProcessError, JournalIntegrityError) as exc:
        raise StudyCloseDeliveryError(
            "historical KPI backfill commit snapshot is invalid"
        ) from exc
    if parent_journal is None:
        raise StudyCloseDeliveryError(
            "historical KPI backfill source ancestry is absent"
        )
    previous = parent_journal if journal.layout == "segmented" else None
    required = _required_paths(journal) | _manifest_transition_paths(
        previous, journal
    )
    changed = frozenset(
        str(
            _git(
                root,
                "diff-tree",
                "--root",
                "--no-commit-id",
                "--name-only",
                "-r",
                commit,
            )
        ).splitlines()
    )
    bindings = tuple(
        CheckpointPathBlob(
            path=path,
            blob=str(_git(root, "rev-parse", f"{commit}:{path}")),
        )
        for path in sorted(required)
    )
    try:
        return build_git_authenticated_backfill_proof(
            events=events,
            ancestry_anchor=ancestry_anchor,
            trailer_commits=commits,
            commit_is_ancestor=_ancestor(root, commit, ancestry_anchor),
            metadata=BackfillCommitMetadata(
                parent=parent, tree=tree, message=message
            ),
            snapshot=BackfillCommitSnapshot(
                events=tuple(commit_events),
                parent_events=tuple(_events(parent_journal)),
                required_path_blobs=bindings,
                changed_paths=changed,
            ),
        )
    except HistoricalBackfillProofError as exc:
        raise StudyCloseDeliveryError(str(exc)) from exc


def _authenticate_historical_backfill_proof(
    root: Path,
    proof: HistoricalKpiBackfillProof | None,
    *,
    checkpoint_parent: str,
) -> None:
    if proof is None:
        return
    parent, tree, message = _commit_parent_tree_message(root, proof.commit)
    observed: dict[str, str] = {}
    try:
        for binding in proof.path_blobs:
            observed[binding.path] = str(
                _git(root, "rev-parse", f"{proof.commit}:{binding.path}")
            )
    except subprocess.CalledProcessError as exc:
        raise StudyCloseDeliveryError(
            "historical KPI backfill path/blob is unavailable"
        ) from exc
    try:
        authenticate_git_backfill_proof(
            proof,
            metadata=BackfillCommitMetadata(
                parent=parent, tree=tree, message=message
            ),
            observed_path_blobs=observed,
            commit_in_anchor=_ancestor(
                root, proof.commit, proof.ancestry_anchor
            ),
            anchor_in_checkpoint_parent=_ancestor(
                root, proof.ancestry_anchor, checkpoint_parent
            ),
        )
    except HistoricalBackfillProofError as exc:
        raise StudyCloseDeliveryError(str(exc)) from exc



def _validate_delivery_checkpoint(*args: Any, **kwargs: Any) -> None:
    try:
        validate_delivery_checkpoint(*args, **kwargs)
    except StudyCloseDeliveryPolicyError as exc:
        raise StudyCloseDeliveryError(str(exc)) from exc



def _full_audit_checkpoint(
    root: Path,
    *,
    journal: JournalSnapshot,
    control_content: bytes,
    kpi_content: bytes,
) -> StudyCloseDeliveryCheckpoint:
    events, cursor = _checkpoint_projection(
        journal=journal,
        control_content=control_content,
        kpi_content=kpi_content,
    )
    close_count, close_chain_digest = _close_chain(_prospective_closes(events))
    parent_main = str(_git(root, "rev-parse", "HEAD"))
    checkpoint = StudyCloseDeliveryCheckpoint(
        basis="full_audit",
        parent_main=parent_main,
        previous_checkpoint_commit=None,
        previous_checkpoint_digest=None,
        cursor=cursor,
        prospective_close_count=close_count,
        prospective_close_chain_digest=close_chain_digest,
        repair_manifest_digest=_repair_manifest_digest_from_index(root),
        control_sha256=sha256(control_content).hexdigest(),
        kpi_sha256=sha256(kpi_content).hexdigest(),
        last_study_close_event_id=None,
        last_study_close_revision=None,
        historical_kpi_backfill=_build_historical_backfill_proof(
            root, events, ancestry_anchor=parent_main
        ),
    )
    _validate_delivery_checkpoint(
        checkpoint,
        kpi_content=kpi_content,
        close_chain=(close_count, close_chain_digest),
        events=events,
        cursor=cursor,
    )
    return checkpoint


def _checkpoint_commit_info(
    root: Path, reference: str = "main"
) -> tuple[str, str, str]:
    try:
        output = str(
            _git(
                root,
                "log",
                "-1",
                "--format=%H%x1f%P%x1f%B",
                reference,
                "--",
                CHECKPOINT_PATH,
            )
        )
    except subprocess.CalledProcessError as exc:
        raise StudyCloseDeliveryError(
            "tracked Study-close checkpoint commit is absent"
        ) from exc
    parts = output.split("\x1f", 2)
    if len(parts) != 3 or not parts[0] or not parts[1]:
        raise StudyCloseDeliveryError(
            "tracked Study-close checkpoint commit is malformed"
        )
    parents = parts[1].split()
    if len(parents) != 1:
        raise StudyCloseDeliveryError(
            "tracked Study-close checkpoint requires one parent"
        )
    return parts[0].strip(), parents[0], parts[2]


def _head_checkpoint(root: Path) -> StudyCloseDeliveryCheckpoint | None:
    content = _optional_git_file(root, "main:", CHECKPOINT_PATH)
    if content is None:
        return None
    try:
        return StudyCloseDeliveryCheckpoint.from_bytes(content)
    except StudyCloseCheckpointError as exc:
        raise StudyCloseDeliveryError(
            "tracked Study-close checkpoint is malformed"
        ) from exc


def _validate_checkpoint_init_trailers(
    message: str, checkpoint: StudyCloseDeliveryCheckpoint
) -> None:
    digest_values = re.findall(
        rf"^{re.escape(_CHECKPOINT_INIT_TRAILER)}:\s*({_DIGEST})\s*$",
        message,
        re.MULTILINE,
    )
    revision_values = re.findall(
        r"^Axiom-State-Revision:\s*([0-9]+)\s*$", message, re.MULTILINE
    )
    expected_suffix = (
        f"{_CHECKPOINT_INIT_TRAILER}: {checkpoint.checkpoint_digest}\n"
        f"Axiom-State-Revision: {checkpoint.cursor.sequence}"
    )
    if (
        digest_values != [checkpoint.checkpoint_digest]
        or revision_values != [str(checkpoint.cursor.sequence)]
        or not message.rstrip().endswith(expected_suffix)
    ):
        raise StudyCloseDeliveryError(
            "checkpoint initialization requires exact checkpoint and revision trailers"
        )


def _authenticate_tracked_checkpoint(
    root: Path,
    *,
    checkpoint: StudyCloseDeliveryCheckpoint,
    checkpoint_content: bytes,
    main_head: str,
) -> tuple[StudyCloseDeliveryCheckpoint, str]:
    main_content = _optional_git_file(root, f"{main_head}:", CHECKPOINT_PATH)
    if main_content is None or checkpoint_content != main_content:
        raise StudyCloseDeliveryError(
            "worktree Study-close checkpoint differs from local main"
        )
    commit, parent, message = _checkpoint_commit_info(root, main_head)
    if parent != checkpoint.parent_main:
        raise StudyCloseDeliveryError(
            "tracked Study-close checkpoint parent main was rewritten"
        )
    changed = set(
        str(
            _git(
                root,
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-r",
                commit,
            )
        ).splitlines()
    )
    if CHECKPOINT_PATH not in changed:
        raise StudyCloseDeliveryError(
            "tracked Study-close checkpoint commit omitted the checkpoint"
        )
    if sha256(_snapshot(root, commit, CONTROL_PATH)).hexdigest() != checkpoint.control_sha256:
        raise StudyCloseDeliveryError("checkpoint commit control hash differs")
    if sha256(_snapshot(root, commit, KPI_PATH)).hexdigest() != checkpoint.kpi_sha256:
        raise StudyCloseDeliveryError("checkpoint commit KPI hash differs")
    _authenticate_historical_backfill_proof(
        root,
        checkpoint.historical_kpi_backfill,
        checkpoint_parent=checkpoint.parent_main,
    )
    if checkpoint.basis in {"full_audit", "checkpoint_upgrade", "maintenance"}:
        _validate_checkpoint_init_trailers(message, checkpoint)
    if checkpoint.basis == "study_close":
        assert checkpoint.last_study_close_event_id is not None
        assert checkpoint.last_study_close_revision is not None
        required = {
            CHECKPOINT_PATH,
            CONTROL_PATH,
            KPI_PATH,
            checkpoint.cursor.journal_path,
        }
        if None in required or not required.issubset(changed):
            raise StudyCloseDeliveryError(
                "Study-close checkpoint commit split required projection paths"
            )
        _validate_trailers(
            message,
            checkpoint.last_study_close_event_id,
            checkpoint.last_study_close_revision,
        )
    if checkpoint.basis != "full_audit":
        previous_commit = checkpoint.previous_checkpoint_commit
        previous_digest = checkpoint.previous_checkpoint_digest
        if previous_commit is None or previous_digest is None:
            raise StudyCloseDeliveryError(
                "Study-close checkpoint previous binding is absent"
            )
        if not _ancestor(root, previous_commit, checkpoint.parent_main):
            raise StudyCloseDeliveryError(
                "previous Study-close checkpoint is not in parent main history"
            )
        try:
            prior = StudyCloseDeliveryCheckpoint.from_bytes(
                _snapshot(root, previous_commit, CHECKPOINT_PATH)
            )
        except (subprocess.CalledProcessError, StudyCloseCheckpointError) as exc:
            raise StudyCloseDeliveryError(
                "previous Study-close checkpoint is unavailable"
            ) from exc
        if prior.checkpoint_digest != previous_digest:
            raise StudyCloseDeliveryError(
                "previous Study-close checkpoint digest differs"
            )
        if checkpoint.schema == CHECKPOINT_SCHEMA:
            transition_closes: tuple[tuple[str, int], ...] = ()
            if checkpoint.basis == "study_close":
                assert checkpoint.last_study_close_event_id is not None
                assert checkpoint.last_study_close_revision is not None
                transition_closes = (
                    (
                        checkpoint.last_study_close_event_id,
                        checkpoint.last_study_close_revision,
                    ),
                )
            _validate_delivery_checkpoint(
                checkpoint,
                kpi_content=_snapshot(root, commit, KPI_PATH),
                previous=prior,
                suffix_closes=transition_closes,
            )
    if _trailer_commits(root, f"{commit}..{main_head}"):
        raise StudyCloseDeliveryError(
            "Study close exists after the tracked delivery checkpoint"
        )
    return checkpoint, commit


@lru_cache(maxsize=8)
def _cached_authenticated_checkpoint(
    root_value: str, main_head: str, checkpoint_content: bytes
) -> tuple[StudyCloseDeliveryCheckpoint, str]:
    """Reuse Git-object authentication only for one exact immutable main head."""

    try:
        checkpoint = StudyCloseDeliveryCheckpoint.from_bytes(checkpoint_content)
    except StudyCloseCheckpointError as exc:
        raise StudyCloseDeliveryError(
            "tracked Study-close checkpoint is malformed"
        ) from exc
    return _authenticate_tracked_checkpoint(
        Path(root_value),
        checkpoint=checkpoint,
        checkpoint_content=checkpoint_content,
        main_head=main_head,
    )


def _checkpoint_from_staged_close(
    root: Path,
    *,
    journal: JournalSnapshot | None = None,
    control_content: bytes | None = None,
    kpi_content: bytes | None = None,
) -> StudyCloseDeliveryCheckpoint:
    require_local_main(root)
    previous = _head_checkpoint(root)
    if previous is None:
        raise StudyCloseDeliveryError(
            "Study close requires an initialized tracked checkpoint"
        )
    if previous.schema != CHECKPOINT_SCHEMA:
        raise StudyCloseDeliveryError(
            "Study close requires the explicit checkpoint v2 full-maintenance upgrade"
        )
    previous_commit, _parent, _message = _checkpoint_commit_info(root)
    if journal is None or control_content is None or kpi_content is None:
        try:
            journal = _index_journal(root)
            control_content = _git(root, "show", f":{CONTROL_PATH}", binary=True)
            kpi_content = _git(root, "show", f":{KPI_PATH}", binary=True)
        except (subprocess.CalledProcessError, JournalIntegrityError) as exc:
            raise StudyCloseDeliveryError(
                "Study close checkpoint requires staged Journal, control, and KPI"
            ) from exc
        assert isinstance(control_content, bytes) and isinstance(kpi_content, bytes)
    assert journal is not None
    assert isinstance(control_content, bytes) and isinstance(kpi_content, bytes)
    events, cursor = _checkpoint_projection(
        journal=journal,
        control_content=control_content,
        kpi_content=kpi_content,
    )
    if previous.cursor.sequence > len(events):
        raise StudyCloseDeliveryError("staged Journal precedes tracked checkpoint")
    if previous.cursor.sequence:
        boundary = events[previous.cursor.sequence - 1]
        framed = canonical_bytes(boundary) + b"\n"
        if (
            boundary.get("event_id") != previous.cursor.event_id
            or boundary.get("previous_event_id")
            != previous.cursor.previous_event_id
            or boundary.get("journal_offset") != previous.cursor.event_offset
            or len(framed) != previous.cursor.event_bytes
            or sha256(framed).hexdigest() != previous.cursor.boundary_sha256
        ):
            raise StudyCloseDeliveryError(
                "staged Journal rewrites tracked checkpoint prefix"
            )
    suffix = events[previous.cursor.sequence :]
    closes = _prospective_closes(suffix)
    if (
        len(closes) != 1
        or not suffix
        or suffix[-1]["event_kind"] != "study_closed"
        or closes[0] != (suffix[-1]["event_id"], suffix[-1]["sequence"])
    ):
        raise StudyCloseDeliveryError(
            "one prospective Study close must end the checkpoint suffix"
        )
    if _repair_manifest_digest_from_index(root) != previous.repair_manifest_digest:
        raise StudyCloseDeliveryError(
            "delivery repair manifest changed outside a full checkpoint audit"
        )
    close_event_id, close_revision = closes[0]
    checkpoint = StudyCloseDeliveryCheckpoint(
        basis="study_close",
        parent_main=str(_git(root, "rev-parse", "HEAD")),
        previous_checkpoint_commit=previous_commit,
        previous_checkpoint_digest=previous.checkpoint_digest,
        cursor=cursor,
        prospective_close_count=previous.prospective_close_count + 1,
        prospective_close_chain_digest=advance_close_chain(
            previous.prospective_close_chain_digest,
            close_event_id,
            close_revision,
        ),
        repair_manifest_digest=previous.repair_manifest_digest,
        control_sha256=sha256(control_content).hexdigest(),
        kpi_sha256=sha256(kpi_content).hexdigest(),
        last_study_close_event_id=close_event_id,
        last_study_close_revision=close_revision,
        historical_kpi_backfill=previous.historical_kpi_backfill,
    )
    _validate_delivery_checkpoint(
        checkpoint,
        kpi_content=kpi_content,
        previous=previous,
        suffix_events=suffix,
    )
    return checkpoint


def _write_tracked_checkpoint(
    root: Path, checkpoint: StudyCloseDeliveryCheckpoint
) -> None:
    path = root / CHECKPOINT_PATH
    content = checkpoint.render()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("wb", buffering=0) as handle:
            if handle.write(content) != len(content):
                raise OSError("short tracked checkpoint write")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def initialize_study_close_delivery_checkpoint(
    repository_root: str | Path,
) -> StudyCloseDeliveryCheckpoint:
    """Create the first tracked checkpoint only after an explicit full audit."""

    root = Path(repository_root).resolve()
    require_local_main(root)
    if _head_checkpoint(root) is not None or (root / CHECKPOINT_PATH).exists():
        raise StudyCloseDeliveryError("tracked Study-close checkpoint already exists")
    unstaged = set(str(_git(root, "diff", "--name-only")).splitlines())
    sensitive = {
        CONTROL_PATH,
        KPI_PATH,
        REPAIR_MANIFEST_PATH,
        *[path for path in unstaged if _journal_path(path)],
    }
    if unstaged & sensitive:
        raise StudyCloseDeliveryError(
            "checkpoint initialization requires all projection inputs staged"
        )
    # This is deliberately expensive and explicit. It is the only path that may
    # turn the already-delivered historical prefix into a tracked high-water.
    _perform_full_audit(root)
    journal = _index_journal(root)
    control_content = _git(root, "show", f":{CONTROL_PATH}", binary=True)
    kpi_content = _git(root, "show", f":{KPI_PATH}", binary=True)
    assert isinstance(control_content, bytes) and isinstance(kpi_content, bytes)
    checkpoint = _full_audit_checkpoint(
        root,
        journal=journal,
        control_content=control_content,
        kpi_content=kpi_content,
    )
    _write_tracked_checkpoint(root, checkpoint)
    return checkpoint


def check_study_close_delivery_checkpoint_v2_upgrade(
    repository_root: str | Path,
    *,
    allow_staged_checkpoint: bool = False,
) -> StudyCloseDeliveryCheckpoint:
    """Fully validate and project, but do not write, the explicit v2 upgrade."""

    root = Path(repository_root).resolve()
    require_local_main(root)
    checkpoint_content = _optional_git_file(root, "main:", CHECKPOINT_PATH)
    if checkpoint_content is None:
        raise StudyCloseDeliveryError(
            "checkpoint v2 upgrade requires the tracked v1 checkpoint"
        )
    main_head = str(_git(root, "rev-parse", "main"))
    previous, previous_commit = _cached_authenticated_checkpoint(
        str(root), main_head, checkpoint_content
    )
    if previous.schema == CHECKPOINT_SCHEMA:
        raise StudyCloseDeliveryError("tracked Study-close checkpoint is already v2")
    if previous.schema != LEGACY_CHECKPOINT_SCHEMA:
        raise StudyCloseDeliveryError("tracked Study-close checkpoint version differs")
    _require_clean_checkpoint_authority_inputs(
        root, allow_staged_checkpoint=allow_staged_checkpoint
    )
    changed = set(str(_git(root, "diff", "--name-only")).splitlines()) | set(
        str(_git(root, "diff", "--cached", "--name-only")).splitlines()
    )
    projection_changes = {
        path
        for path in changed
        if path in {CONTROL_PATH, KPI_PATH, CHECKPOINT_PATH}
        or _journal_path(path)
    }
    if allow_staged_checkpoint:
        projection_changes.discard(CHECKPOINT_PATH)
    if projection_changes:
        raise StudyCloseDeliveryError(
            "checkpoint v2 upgrade requires clean projection paths"
        )
    _perform_full_audit(root)
    try:
        journal = _commit_journal(root, main_head, validate_events=True)
        control_content = _snapshot(root, main_head, CONTROL_PATH)
        kpi_content = _snapshot(root, main_head, KPI_PATH)
    except (OSError, subprocess.CalledProcessError, JournalIntegrityError) as exc:
        raise StudyCloseDeliveryError(
            "checkpoint v2 upgrade snapshot is invalid"
        ) from exc
    events, cursor = _checkpoint_projection(
        journal=journal,
        control_content=control_content,
        kpi_content=kpi_content,
    )
    if previous.cursor.sequence > len(events):
        raise StudyCloseDeliveryError("legacy checkpoint exceeds current Journal")
    suffix = events[previous.cursor.sequence :]
    close_count, close_chain_digest = _close_chain(_prospective_closes(events))
    checkpoint = project_checkpoint_v2_upgrade(
        previous=previous,
        previous_commit=previous_commit,
        parent_main=main_head,
        cursor=cursor,
        close_chain=(close_count, close_chain_digest),
        repair_manifest_digest=_repair_manifest_digest_from_index(root),
        control_content=control_content,
        kpi_content=kpi_content,
        historical_kpi_backfill=_build_historical_backfill_proof(
            root, events, ancestry_anchor=main_head
        ),
    )
    _validate_delivery_checkpoint(
        checkpoint,
        kpi_content=kpi_content,
        previous=previous,
        suffix_events=suffix,
    )
    return checkpoint


def prepare_study_close_delivery_checkpoint_v2_upgrade(
    repository_root: str | Path,
) -> StudyCloseDeliveryCheckpoint:
    """Write the explicitly full-audited v2 upgrade for a later coherent commit."""

    root = Path(repository_root).resolve()
    checkpoint = check_study_close_delivery_checkpoint_v2_upgrade(root)
    _write_tracked_checkpoint(root, checkpoint)
    return checkpoint


def check_study_close_delivery_checkpoint_maintenance(
    repository_root: str | Path,
    *,
    allow_staged_checkpoint: bool = False,
) -> StudyCloseDeliveryCheckpoint:
    """Fully audit and project one v2 no-close cursor-only maintenance step."""

    root = Path(repository_root).resolve()
    require_local_main(root)
    checkpoint_content = _optional_git_file(root, "main:", CHECKPOINT_PATH)
    if checkpoint_content is None:
        raise StudyCloseDeliveryError(
            "checkpoint maintenance requires the tracked v2 checkpoint"
        )
    main_head = str(_git(root, "rev-parse", "main"))
    previous, previous_commit = _cached_authenticated_checkpoint(
        str(root), main_head, checkpoint_content
    )
    if previous.schema != CHECKPOINT_SCHEMA:
        raise StudyCloseDeliveryError("checkpoint maintenance requires v2")
    _require_clean_checkpoint_authority_inputs(
        root, allow_staged_checkpoint=allow_staged_checkpoint
    )
    _perform_full_audit(root)
    try:
        journal = _commit_journal(root, main_head, validate_events=True)
        control_content = _snapshot(root, main_head, CONTROL_PATH)
        kpi_content = _snapshot(root, main_head, KPI_PATH)
    except (OSError, subprocess.CalledProcessError, JournalIntegrityError) as exc:
        raise StudyCloseDeliveryError(
            "checkpoint maintenance snapshot is invalid"
        ) from exc
    events, cursor = _checkpoint_projection(
        journal=journal,
        control_content=control_content,
        kpi_content=kpi_content,
    )
    if previous.cursor.sequence > len(events):
        raise StudyCloseDeliveryError("checkpoint maintenance Journal regressed")
    suffix = events[previous.cursor.sequence :]
    suffix_closes = _prospective_closes(suffix)
    if suffix_closes:
        raise StudyCloseDeliveryError(
            "checkpoint maintenance cannot absorb a Study close"
        )
    close_count, close_chain_digest = _close_chain(_prospective_closes(events))
    if (
        close_count != previous.prospective_close_count
        or close_chain_digest != previous.prospective_close_chain_digest
    ):
        raise StudyCloseDeliveryError(
            "checkpoint maintenance changed the authenticated close chain"
        )
    checkpoint = project_checkpoint_maintenance(
        previous=previous,
        previous_commit=previous_commit,
        parent_main=main_head,
        cursor=cursor,
        repair_manifest_digest=_repair_manifest_digest_from_index(root),
        control_content=control_content,
        kpi_content=kpi_content,
    )
    _validate_delivery_checkpoint(
        checkpoint,
        kpi_content=kpi_content,
        previous=previous,
        suffix_closes=suffix_closes,
    )
    return checkpoint


def prepare_study_close_delivery_checkpoint_maintenance(
    repository_root: str | Path,
) -> StudyCloseDeliveryCheckpoint:
    """Write one explicit full-maintenance v2 no-close cursor checkpoint."""

    root = Path(repository_root).resolve()
    checkpoint = check_study_close_delivery_checkpoint_maintenance(root)
    _write_tracked_checkpoint(root, checkpoint)
    return checkpoint



def check_study_close_delivery_checkpoint(
    repository_root: str | Path,
    *,
    allowed_milestone_paths: Sequence[str] = (),
) -> StudyCloseCheckpointPlan:
    """Validate exact staging and render one checkpoint without writing it."""

    root = Path(repository_root).resolve()
    require_local_main(root)
    try:
        allowed = canonical_milestone_paths(allowed_milestone_paths)
    except StudyCloseDeliveryPolicyError as exc:
        raise StudyCloseDeliveryError(str(exc)) from exc
    try:
        journal = _index_journal(root)
        control_content = _git(root, "show", f":{CONTROL_PATH}", binary=True)
        kpi_content = _git(root, "show", f":{KPI_PATH}", binary=True)
    except (subprocess.CalledProcessError, JournalIntegrityError) as exc:
        raise StudyCloseDeliveryError(
            "checkpoint preflight requires staged Journal, control, and KPI"
        ) from exc
    assert isinstance(control_content, bytes) and isinstance(kpi_content, bytes)
    previous = _head_journal(root)
    projection_paths = _required_paths(journal) | _manifest_transition_paths(
        previous, journal
    )
    staged = set(str(_git(root, "diff", "--cached", "--name-only")).splitlines())
    unstaged = set(str(_git(root, "diff", "--name-only")).splitlines())
    try:
        expected = exact_staging_paths(
            projection_paths=tuple(projection_paths),
            allowed_milestone_paths=allowed,
            staged_paths=tuple(staged),
            unstaged_paths=tuple(unstaged),
            protected_paths=(
                CONTROL_PATH,
                KPI_PATH,
                *tuple(path for path in projection_paths if _journal_path(path)),
            ),
        )
    except StudyCloseDeliveryPolicyError as exc:
        raise StudyCloseDeliveryError(str(exc)) from exc
    checkpoint = _checkpoint_from_staged_close(
        root,
        journal=journal,
        control_content=control_content,
        kpi_content=kpi_content,
    )
    return StudyCloseCheckpointPlan(
        checkpoint=checkpoint,
        required_staged_paths=expected,
        allowed_milestone_paths=allowed,
    )


def prepare_study_close_delivery_checkpoint(
    repository_root: str | Path,
    *,
    allowed_milestone_paths: Sequence[str] = (),
) -> StudyCloseDeliveryCheckpoint:
    """Render the exact checkpoint that must accompany one staged Study close."""

    root = Path(repository_root).resolve()
    plan = check_study_close_delivery_checkpoint(
        root, allowed_milestone_paths=allowed_milestone_paths
    )
    checkpoint = plan.checkpoint
    _write_tracked_checkpoint(root, checkpoint)
    return checkpoint


def _advance_close_chain(current: str, event_id: str, revision: int) -> str:
    return sha256(
        canonical_bytes(
            {
                "previous_digest": current,
                "state_revision": revision,
                "study_close_event_id": event_id,
            }
        )
    ).hexdigest()


def _close_chain(closes: Sequence[tuple[str, int]]) -> tuple[int, str]:
    digest = _EMPTY_CLOSE_CHAIN_DIGEST
    for event_id, revision in closes:
        digest = _advance_close_chain(digest, event_id, revision)
    return len(closes), digest


def _cache_body(
    *,
    main_head: str,
    repair_manifest_digest: str | None,
    cursor: _JournalCursor,
    close_count: int,
    close_chain_digest: str,
) -> dict[str, Any]:
    return {
        "journal_cursor": cursor.payload(),
        "main_head": main_head,
        "prospective_close_chain_digest": close_chain_digest,
        "prospective_close_count": close_count,
        "repair_manifest_digest": repair_manifest_digest,
        "schema": _AUDIT_CACHE_SCHEMA,
        "validator_version": _AUDIT_VALIDATOR_VERSION,
    }


def _write_audit_cache(root: Path, body: Mapping[str, Any]) -> None:
    path = _cache_path(root)
    payload = {**body, "cache_digest": sha256(canonical_bytes(body)).hexdigest()}
    content = canonical_bytes(payload) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("wb", buffering=0) as handle:
            if handle.write(content) != len(content):
                raise OSError("short audit cache write")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _load_audit_cache(root: Path) -> tuple[dict[str, Any], _JournalCursor] | None:
    path = _cache_path(root)
    try:
        content = path.read_bytes()
    except OSError:
        return None
    try:
        if not content.endswith(b"\n") or content.count(b"\n") != 1:
            raise _AuditCacheStale("audit cache framing differs")
        value = parse_canonical(content[:-1])
        expected = {
            "cache_digest",
            "journal_cursor",
            "main_head",
            "prospective_close_chain_digest",
            "prospective_close_count",
            "repair_manifest_digest",
            "schema",
            "validator_version",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise _AuditCacheStale("audit cache fields differ")
        cache_digest = value["cache_digest"]
        body = dict(value)
        del body["cache_digest"]
        if (
            _digest(cache_digest, "audit cache digest")
            != sha256(canonical_bytes(body)).hexdigest()
        ):
            raise _AuditCacheStale("audit cache digest differs")
        if (
            body["schema"] != _AUDIT_CACHE_SCHEMA
            or body["validator_version"] != _AUDIT_VALIDATOR_VERSION
        ):
            raise _AuditCacheStale("audit cache version differs")
        _commit_identity(body["main_head"], "cached main head")
        repair_digest = body["repair_manifest_digest"]
        if repair_digest is not None:
            _digest(repair_digest, "cached repair manifest digest")
        close_count = body["prospective_close_count"]
        if (
            isinstance(close_count, bool)
            or not isinstance(close_count, int)
            or close_count < 0
        ):
            raise _AuditCacheStale("cached prospective close count is invalid")
        close_chain_digest = _digest(
            body["prospective_close_chain_digest"],
            "cached prospective close chain digest",
        )
        cursor = _cursor_from_mapping(body["journal_cursor"])
        if close_count > cursor.sequence or (
            close_count == 0 and close_chain_digest != _EMPTY_CLOSE_CHAIN_DIGEST
        ):
            raise _AuditCacheStale("cached prospective close high-water differs")
        return body, cursor
    except (OSError, TypeError, ValueError, _AuditCacheStale):
        return None


def _index_journal(root: Path) -> JournalSnapshot:
    paths = _journal_paths_from_git(
        root,
        "ls-files",
        "--cached",
        "--",
        LEGACY_JOURNAL_RELATIVE_PATH,
        JOURNAL_DIRECTORY_RELATIVE_PATH,
    )
    available = set(paths)
    return read_journal_snapshot(
        lambda path: (
            _optional_git_file(root, ":", path) if path in available else None
        ),
        listed_paths=paths,
    )


def _commit_journal(
    root: Path, commit: str, *, validate_events: bool = False
) -> JournalSnapshot:
    paths = _journal_paths_from_git(
        root,
        "ls-tree",
        "-r",
        "--name-only",
        commit,
        "--",
        LEGACY_JOURNAL_RELATIVE_PATH,
        JOURNAL_DIRECTORY_RELATIVE_PATH,
    )
    available = set(paths)
    return read_journal_snapshot(
        lambda path: (
            _optional_git_file(root, f"{commit}:", path)
            if path in available
            else None
        ),
        listed_paths=paths,
        validate_events=validate_events,
    )


def _journal_path(path: str) -> bool:
    return path == LEGACY_JOURNAL_RELATIVE_PATH or path.startswith(
        JOURNAL_DIRECTORY_RELATIVE_PATH + "/"
    )


def _events(snapshot: JournalSnapshot) -> list[dict[str, Any]]:
    return [dict(event) for event in snapshot.events]


def render_projection(events: Sequence[Mapping[str, Any]]) -> bytes:
    event_times = {event["event_id"]: event["occurred_at_utc"] for event in events}
    rows: list[StudyKpiProjectionRow] = []
    for event in events:
        for record in event.get("index_records", []):
            if record.get("kind") != "study-kpi":
                continue
            payload = record["payload"]
            closed_at = (
                event["occurred_at_utc"]
                if payload["provenance"] == "prospective_close"
                else event_times[payload["historical_study_close_event_id"]]
            )
            metrics = payload["metrics"]
            rows.append(
                StudyKpiProjectionRow(
                    sequence=payload["sequence"],
                    closed_at_utc=closed_at,
                    study_id=payload["study_id"],
                    executable_id=payload["executable_id"],
                    executable_display_id=payload["executable_display_id"],
                    net_profit_micropoints=metrics["net_profit_micropoints"],
                    median_fold_profit_factor_milli=metrics[
                        "median_fold_profit_factor_milli"
                    ],
                    trade_count=metrics["trade_count"],
                    monthly_realized_exit_drawdown_share_of_gross_profit_ppm=(
                        metrics[
                            "monthly_realized_exit_drawdown_share_of_gross_profit_ppm"
                        ]
                    ),
                    outcome=payload["outcome"],
                )
            )
    return render_study_kpi(rows)


def _validate_boundary(
    *, control: Mapping[str, Any], events: Sequence[Mapping[str, Any]]
) -> tuple[str, int]:
    if not events:
        raise StudyCloseDeliveryError("Study-close Journal snapshot is empty")
    tail = events[-1]
    event_id = tail["event_id"]
    revision = tail["sequence"]
    if (
        tail["event_kind"] != "study_closed"
        or control["revision"] != revision
        or control["heads"]["journal"]["event_id"] != event_id
    ):
        raise StudyCloseDeliveryError("staged Study-close boundary differs")
    return event_id, revision


def _validate_trailers(message: str, event_id: str, revision: int) -> None:
    close_values = re.findall(
        rf"^Axiom-Study-Close:\s*({_DIGEST})\s*$", message, re.MULTILINE
    )
    revision_values = re.findall(
        r"^Axiom-State-Revision:\s*([0-9]+)\s*$", message, re.MULTILINE
    )
    expected_suffix = (
        f"Axiom-Study-Close: {event_id}\n"
        f"Axiom-State-Revision: {revision}"
    )
    if (
        close_values != [event_id]
        or revision_values != [str(revision)]
        or not message.rstrip().endswith(expected_suffix)
    ):
        raise StudyCloseDeliveryError(
            "Study-close commit requires exact Axiom-Study-Close and "
            "Axiom-State-Revision trailers"
        )


def _required_paths(snapshot: JournalSnapshot) -> set[str]:
    if snapshot.active_path is None:
        raise StudyCloseDeliveryError("Study-close Journal has no active path")
    return {CONTROL_PATH, KPI_PATH, snapshot.active_path}


def _manifest_transition_paths(
    previous: JournalSnapshot | None, current: JournalSnapshot
) -> set[str]:
    if current.layout != "segmented":
        return set()
    if previous is not None and previous.layout == "segmented":
        if previous.manifest_path == current.manifest_path:
            previous_paths = set(previous.journal_paths)
            current_paths = set(current.journal_paths)
            if previous_paths == current_paths:
                return set()
            return {
                JOURNAL_MANIFEST_RELATIVE_PATH,
                *(current_paths - previous_paths),
            }
    return {JOURNAL_MANIFEST_RELATIVE_PATH, *current.journal_paths}


def _head_journal(root: Path) -> JournalSnapshot | None:
    try:
        _git(root, "rev-parse", "--verify", "HEAD")
    except subprocess.CalledProcessError:
        return None
    try:
        return _commit_journal(root, "HEAD")
    except JournalIntegrityError as exc:
        raise StudyCloseDeliveryError("HEAD Journal snapshot is invalid") from exc


def _tracked_checkpoint_required_by_main(root: Path) -> bool:
    content = _optional_git_file(root, "main:", "contracts/operations.yaml")
    return bool(
        content is not None
        and f"tracked_checkpoint: {CHECKPOINT_PATH}".encode("ascii") in content
    )


def validate_commit_message(repository_root: str | Path, message_path: str | Path) -> None:
    root = Path(repository_root).resolve()
    staged = set(str(_git(root, "diff", "--cached", "--name-only")).splitlines())
    unstaged = set(str(_git(root, "diff", "--name-only")).splitlines())
    journal_delta = {path for path in staged | unstaged if _journal_path(path)}
    try:
        worktree = _worktree_journal(root)
    except (OSError, JournalIntegrityError) as exc:
        if journal_delta:
            raise StudyCloseDeliveryError("worktree Journal snapshot is invalid") from exc
        return
    worktree_events = _events(worktree)
    pending_close = bool(
        worktree_events
        and worktree_events[-1]["event_kind"] == "study_closed"
        and (
            journal_delta
            or bool((staged | unstaged) & set(BASE_REQUIRED_PATHS))
        )
    )
    message = Path(message_path).read_text(encoding="utf-8")
    head_checkpoint = _head_checkpoint(root)
    checkpoint_staged = CHECKPOINT_PATH in staged
    checkpoint_unstaged = CHECKPOINT_PATH in unstaged
    if pending_close or checkpoint_staged or checkpoint_unstaged:
        require_local_main(root)
    if head_checkpoint is None and checkpoint_staged:
        if pending_close or checkpoint_unstaged:
            raise StudyCloseDeliveryError(
                "initial checkpoint migration cannot include a prospective Study close"
            )
        unstaged_projection = {
            path
            for path in unstaged
            if path in {
                CONTROL_PATH,
                KPI_PATH,
                REPAIR_MANIFEST_PATH,
            }
            or _journal_path(path)
        }
        if unstaged_projection:
            raise StudyCloseDeliveryError(
                "checkpoint initialization projection inputs must be fully staged"
            )
        # Independently repeat the expensive audit in the hook. The generator
        # is convenience, not authority for the initial high-water.
        _perform_full_audit(root)
        try:
            staged_snapshot = _index_journal(root)
            staged_control = _git(root, "show", f":{CONTROL_PATH}", binary=True)
            staged_kpi = _git(root, "show", f":{KPI_PATH}", binary=True)
            staged_checkpoint = _git(
                root, "show", f":{CHECKPOINT_PATH}", binary=True
            )
        except (subprocess.CalledProcessError, JournalIntegrityError) as exc:
            raise StudyCloseDeliveryError(
                "checkpoint initialization staged snapshot is incomplete"
            ) from exc
        assert isinstance(staged_control, bytes)
        assert isinstance(staged_kpi, bytes)
        assert isinstance(staged_checkpoint, bytes)
        expected = _full_audit_checkpoint(
            root,
            journal=staged_snapshot,
            control_content=staged_control,
            kpi_content=staged_kpi,
        )
        if staged_checkpoint != expected.render():
            raise StudyCloseDeliveryError(
                "staged checkpoint does not equal the full-audit projection"
            )
        _validate_checkpoint_init_trailers(message, expected)
        return
    if head_checkpoint is None and checkpoint_unstaged:
        raise StudyCloseDeliveryError(
            "untracked checkpoint bytes cannot enter a commit"
        )
    if (
        head_checkpoint is not None
        and head_checkpoint.schema == LEGACY_CHECKPOINT_SCHEMA
        and checkpoint_staged
        and not pending_close
    ):
        if checkpoint_unstaged or staged != {CHECKPOINT_PATH}:
            raise StudyCloseDeliveryError(
                "checkpoint v2 upgrade must be one exact checkpoint-only milestone"
            )
        try:
            staged_content = _git(
                root, "show", f":{CHECKPOINT_PATH}", binary=True
            )
            assert isinstance(staged_content, bytes)
            staged_checkpoint = StudyCloseDeliveryCheckpoint.from_bytes(
                staged_content
            )
        except (
            AssertionError,
            subprocess.CalledProcessError,
            StudyCloseCheckpointError,
        ) as exc:
            raise StudyCloseDeliveryError(
                "staged checkpoint v2 upgrade is malformed"
            ) from exc
        if (
            staged_checkpoint.schema != CHECKPOINT_SCHEMA
            or staged_checkpoint.basis != "checkpoint_upgrade"
        ):
            raise StudyCloseDeliveryError(
                "staged checkpoint is not the explicit v2 upgrade"
            )
        expected = check_study_close_delivery_checkpoint_v2_upgrade(
            root, allow_staged_checkpoint=True
        )
        if staged_content != expected.render():
            raise StudyCloseDeliveryError(
                "staged checkpoint v2 upgrade differs from the full audit"
            )
        _validate_checkpoint_init_trailers(message, expected)
        return
    if (
        head_checkpoint is not None
        and head_checkpoint.schema == CHECKPOINT_SCHEMA
        and checkpoint_staged
        and not pending_close
    ):
        if checkpoint_unstaged or staged != {CHECKPOINT_PATH}:
            raise StudyCloseDeliveryError(
                "checkpoint maintenance must be one exact checkpoint-only milestone"
            )
        try:
            staged_content = _git(
                root, "show", f":{CHECKPOINT_PATH}", binary=True
            )
            assert isinstance(staged_content, bytes)
            staged_checkpoint = StudyCloseDeliveryCheckpoint.from_bytes(
                staged_content
            )
        except (
            AssertionError,
            subprocess.CalledProcessError,
            StudyCloseCheckpointError,
        ) as exc:
            raise StudyCloseDeliveryError(
                "staged checkpoint maintenance is malformed"
            ) from exc
        if staged_checkpoint.basis != "maintenance":
            raise StudyCloseDeliveryError(
                "staged no-close checkpoint is not maintenance"
            )
        expected = check_study_close_delivery_checkpoint_maintenance(
            root, allow_staged_checkpoint=True
        )
        if staged_content != expected.render():
            raise StudyCloseDeliveryError(
                "staged checkpoint maintenance differs from the full audit"
            )
        _validate_checkpoint_init_trailers(message, expected)
        return
    if head_checkpoint is not None and (checkpoint_staged or checkpoint_unstaged):
        if not pending_close or checkpoint_unstaged:
            raise StudyCloseDeliveryError(
                "tracked checkpoint changes only with one fully staged Study close"
            )
    staged_journal_delta = {path for path in staged if _journal_path(path)}
    if not pending_close and not staged_journal_delta:
        return
    try:
        staged_snapshot = _index_journal(root)
    except (OSError, JournalIntegrityError) as exc:
        if pending_close:
            raise StudyCloseDeliveryError(
                "pending Study close requires a complete staged Journal snapshot"
            ) from exc
        return
    staged_events = _events(staged_snapshot)
    if not staged_events or staged_events[-1]["event_kind"] != "study_closed":
        if pending_close:
            raise StudyCloseDeliveryError(
                "pending Study close cannot be split across commits"
            )
        return
    previous = _head_journal(root)
    required = _required_paths(staged_snapshot) | _manifest_transition_paths(
        previous, staged_snapshot
    )
    if head_checkpoint is not None:
        required.add(CHECKPOINT_PATH)
    elif _tracked_checkpoint_required_by_main(root):
        raise StudyCloseDeliveryError(
            "prospective Study close requires the tracked checkpoint"
        )
    unreferenced = staged_journal_delta - set(staged_snapshot.journal_paths)
    if unreferenced:
        raise StudyCloseDeliveryError(
            "Study close stages an unreferenced Journal segment"
        )
    if not required.issubset(staged) or required & unstaged:
        raise StudyCloseDeliveryError(
            "Study close requires state, active Journal paths, and KPI staged together"
        )
    try:
        staged_control = _git(root, "show", f":{CONTROL_PATH}", binary=True)
        staged_kpi = _git(root, "show", f":{KPI_PATH}", binary=True)
    except subprocess.CalledProcessError as exc:
        raise StudyCloseDeliveryError(
            "pending Study close requires all projection paths staged"
        ) from exc
    assert isinstance(staged_control, bytes) and isinstance(staged_kpi, bytes)
    event_id, revision = _validate_boundary(
        control=json.loads(staged_control), events=staged_events
    )
    if staged_kpi != render_projection(staged_events):
        raise StudyCloseDeliveryError("staged Study KPI projection differs")
    _validate_trailers(message, event_id, revision)
    if head_checkpoint is not None:
        expected_checkpoint = _checkpoint_from_staged_close(
            root,
            journal=staged_snapshot,
            control_content=staged_control,
            kpi_content=staged_kpi,
        )
        try:
            staged_checkpoint = _git(
                root, "show", f":{CHECKPOINT_PATH}", binary=True
            )
        except subprocess.CalledProcessError as exc:
            raise StudyCloseDeliveryError(
                "Study close omitted the staged tracked checkpoint"
            ) from exc
        assert isinstance(staged_checkpoint, bytes)
        if staged_checkpoint != expected_checkpoint.render():
            raise StudyCloseDeliveryError(
                "staged Study-close checkpoint projection differs"
            )


def _prospective_closes(events: Sequence[Mapping[str, Any]]) -> list[tuple[str, int]]:
    return prospective_closes(events)


def _trailer_commits(
    root: Path, reference: str = "main"
) -> dict[tuple[str, int], list[str]]:
    output = str(_git(root, "log", reference, "--format=%H%x1f%B%x1e"))
    result: dict[tuple[str, int], list[str]] = {}
    for row in output.split("\x1e"):
        parts = row.strip().split("\x1f", 1)
        if len(parts) != 2:
            continue
        close_values = re.findall(
            rf"^Axiom-Study-Close:\s*({_DIGEST})\s*$",
            parts[1],
            re.MULTILINE,
        )
        revision_values = re.findall(
            r"^Axiom-State-Revision:\s*([0-9]+)\s*$",
            parts[1],
            re.MULTILINE,
        )
        if len(close_values) == 1 and len(revision_values) == 1:
            result.setdefault(
                (close_values[0], int(revision_values[0])), []
            ).append(parts[0].strip())
    return result


def _parent_journal(root: Path, commit: str) -> JournalSnapshot | None:
    try:
        parent = str(_git(root, "rev-parse", f"{commit}^"))
    except subprocess.CalledProcessError:
        return None
    return _commit_journal(root, parent)


def _validate_snapshot(root: Path, commit: str, event_id: str, revision: int) -> None:
    if not _ancestor(root, commit, "main"):
        raise StudyCloseDeliveryError("Study-close commit is not on local main")
    changed = set(
        str(
            _git(
                root,
                "diff-tree",
                "--root",
                "--no-commit-id",
                "--name-only",
                "-r",
                commit,
            )
        ).splitlines()
    )
    try:
        journal = _commit_journal(root, commit)
        previous = (
            _parent_journal(root, commit)
            if journal.layout == "segmented"
            else None
        )
    except (OSError, JournalIntegrityError) as exc:
        raise StudyCloseDeliveryError("Study-close commit Journal is invalid") from exc
    required = _required_paths(journal) | _manifest_transition_paths(previous, journal)
    changed_journal = {path for path in changed if _journal_path(path)}
    if changed_journal - set(journal.journal_paths):
        raise StudyCloseDeliveryError(
            "Study-close commit changed an unreferenced Journal segment"
        )
    if not required.issubset(changed):
        raise StudyCloseDeliveryError("Study-close commit split required paths")
    events = _events(journal)
    control = json.loads(_snapshot(root, commit, CONTROL_PATH))
    observed_event, observed_revision = _validate_boundary(
        control=control, events=events
    )
    if observed_event != event_id or observed_revision != revision:
        raise StudyCloseDeliveryError("Study-close commit snapshot differs")
    if _snapshot(root, commit, KPI_PATH) != render_projection(events):
        raise StudyCloseDeliveryError("Study-close commit KPI differs")


def _perform_full_audit(
    root: Path,
) -> tuple[JournalSnapshot, list[tuple[str, int]]]:
    try:
        journal = _worktree_journal(root)
        events = _events(journal)
    except (OSError, JournalIntegrityError) as exc:
        raise StudyCloseDeliveryError("worktree Journal audit failed") from exc
    trailer_commits = _trailer_commits(root)
    repair_path = root / REPAIR_MANIFEST_PATH
    repaired: dict[tuple[str, int], str] = {}
    if repair_path.is_file():
        repair = json.loads(repair_path.read_bytes())
        repaired = {
            (entry["study_close_event_id"], entry["state_revision"]): entry[
                "original_commit"
            ]
            for entry in repair.get("entries", [])
        }
        manifest_hash = sha256(repair_path.read_bytes()).hexdigest()
        attestation = str(_git(root, "log", "main", "--format=%H%x1f%B%x1e"))
        matches = []
        for row in attestation.split("\x1e"):
            parts = row.strip().split("\x1f", 1)
            if len(parts) != 2:
                continue
            values = re.findall(
                rf"^Axiom-Study-Close-Delivery-Repair:\s*({_DIGEST})\s*$",
                parts[1],
                re.MULTILINE,
            )
            if values == [manifest_hash]:
                matches.append(parts[0].strip())
        if repaired and len(matches) != 1:
            raise StudyCloseDeliveryError("delivery repair attestation is absent")
    for close_event_id, close_revision in _prospective_closes(events):
        commits = trailer_commits.get((close_event_id, close_revision), [])
        if len(commits) == 1:
            _validate_snapshot(root, commits[0], close_event_id, close_revision)
            continue
        repaired_commit = repaired.get((close_event_id, close_revision))
        if len(commits) == 0 and repaired_commit is not None:
            _validate_snapshot(root, repaired_commit, close_event_id, close_revision)
            continue
        raise StudyCloseDeliveryError(
            f"Study close {close_event_id} revision {close_revision} "
            "lacks one authenticated commit"
        )
    return journal, _prospective_closes(events)


def _best_effort_write_cache(root: Path, body: Mapping[str, Any]) -> None:
    try:
        _write_audit_cache(root, body)
    except OSError:
        # This file is an ignored optimization. Delivery authority remains Git,
        # the Journal, control, KPI, and (where present) the repair attestation.
        pass


def audit_all_study_close_deliveries(repository_root: str | Path) -> None:
    """Rebuild the local high-water cache after auditing every Study close."""

    root = Path(repository_root).resolve()
    _require_git_repository(root)
    journal, closes = _perform_full_audit(root)
    try:
        control_content = (root / CONTROL_PATH).read_bytes()
        kpi_content = (root / KPI_PATH).read_bytes()
    except OSError as exc:
        raise StudyCloseDeliveryError(
            "full Study-close audit projection is unavailable"
        ) from exc
    _full_audit_checkpoint(
        root,
        journal=journal,
        control_content=control_content,
        kpi_content=kpi_content,
    )
    cursor = _cursor_from_snapshot(root, journal)
    close_count, close_chain_digest = _close_chain(closes)
    main_head = str(_git(root, "rev-parse", "main"))
    _best_effort_write_cache(
        root,
        _cache_body(
            main_head=main_head,
            repair_manifest_digest=_repair_manifest_digest(root),
            cursor=cursor,
            close_count=close_count,
            close_chain_digest=close_chain_digest,
        ),
    )


def _inspect_tracked_study_close_delivery(
    root: Path,
) -> tuple[StudyCloseDeliveryCheckpoint, str, str]:
    """Authenticate the tracked checkpoint and local suffix without I/O writes."""

    checkpoint_path = root / CHECKPOINT_PATH
    try:
        checkpoint_content = checkpoint_path.read_bytes()
    except OSError as exc:
        raise StudyCloseDeliveryError(
            "tracked Study-close checkpoint is unavailable"
        ) from exc
    main_head = str(_git(root, "rev-parse", "main"))
    checkpoint, checkpoint_commit = _cached_authenticated_checkpoint(
        str(root), main_head, checkpoint_content
    )
    if checkpoint.repair_manifest_digest != _repair_manifest_digest(root):
        raise StudyCloseDeliveryError(
            "delivery repair manifest differs from tracked checkpoint"
        )
    try:
        suffix_events, next_cursor = _scan_tracked_journal_suffix(
            root, checkpoint.cursor
        )
    except _AuditCacheStale as exc:
        raise StudyCloseDeliveryError(
            f"tracked Study-close Journal suffix is invalid: {exc}"
        ) from exc
    new_closes = _prospective_closes(suffix_events)
    if new_closes:
        raise StudyCloseDeliveryError(
            "Study close exists after the tracked delivery checkpoint"
        )
    try:
        current_kpi = (root / KPI_PATH).read_bytes()
        current_control = json.loads((root / CONTROL_PATH).read_bytes())
        if (
            current_control["revision"] != next_cursor.sequence
            or current_control["heads"]["journal"]["sequence"]
            != next_cursor.sequence
            or current_control["heads"]["journal"]["event_id"]
            != next_cursor.event_id
        ):
            raise StudyCloseCheckpointError(
                "current control and Journal suffix heads differ"
            )
        validate_no_close_suffix(
            checkpoint,
            suffix_closes=new_closes,
            current_cursor=next_cursor,
            current_kpi_sha256=sha256(current_kpi).hexdigest(),
        )
    except (OSError, KeyError, TypeError, ValueError, StudyCloseCheckpointError) as exc:
        raise StudyCloseDeliveryError(
            "tracked Study-close current projection is invalid"
        ) from exc
    return checkpoint, checkpoint_commit, main_head


def inspect_tracked_study_close_delivery(
    repository_root: str | Path,
    *,
    capability: StudyCloseGuardCapability | None = None,
) -> StudyCloseDeliveryCheckpoint:
    """Read-only local authentication for planning and diagnostics."""

    root = Path(repository_root).resolve()
    if not _require_git_repository(root, capability=capability):
        raise StudyCloseDeliveryError(
            "tracked Study-close inspection requires a Git repository"
        )
    if not (root / CHECKPOINT_PATH).is_file():
        raise StudyCloseDeliveryError(
            "tracked Study-close checkpoint is unavailable"
        )
    checkpoint, _checkpoint_commit, _main_head = (
        _inspect_tracked_study_close_delivery(root)
    )
    return checkpoint


def require_all_study_close_deliveries(
    repository_root: str | Path,
    *,
    capability: StudyCloseGuardCapability | None = None,
) -> None:
    """Guard the boundary from a verified high-water plus the new suffix."""

    root = Path(repository_root).resolve()
    if not _require_git_repository(root, capability=capability):
        return
    checkpoint_path = root / CHECKPOINT_PATH
    if checkpoint_path.is_file():
        checkpoint, checkpoint_commit, main_head = (
            _inspect_tracked_study_close_delivery(root)
        )
        _ensure_origin_delivery_observed(
            str(root),
            main_head,
            checkpoint.checkpoint_digest,
            checkpoint_commit,
        )
        return
    if _head_checkpoint(root) is not None:
        raise StudyCloseDeliveryError(
            "tracked Study-close checkpoint is unavailable"
        )
    if _tracked_checkpoint_required_by_main(root):
        raise StudyCloseDeliveryError(
            "tracked Study-close delivery checkpoint is absent"
        )
    # Transitional compatibility before the operations authority activates the
    # tracked checkpoint. Once activated, the ignored cache is never authority.
    cached = _load_audit_cache(root)
    if cached is None:
        audit_all_study_close_deliveries(root)
        return
    body, cursor = cached
    if body["repair_manifest_digest"] != _repair_manifest_digest(root):
        audit_all_study_close_deliveries(root)
        return
    main_head = str(_git(root, "rev-parse", "main"))
    cached_main = body["main_head"]
    if cached_main != main_head and not _ancestor(root, cached_main, main_head):
        raise StudyCloseDeliveryError(
            "cached Study-close main high-water was rewritten"
        )
    try:
        suffix_events, next_cursor = _scan_journal_suffix(root, cursor)
    except _AuditCacheStale:
        audit_all_study_close_deliveries(root)
        return
    new_closes = _prospective_closes(suffix_events)
    trailer_commits = (
        _trailer_commits(root, f"{cached_main}..{main_head}")
        if cached_main != main_head
        else {}
    )
    expected = set(new_closes)
    observed = set(trailer_commits)
    if observed != expected:
        raise StudyCloseDeliveryError(
            "main advance and Journal Study-close suffix differ"
        )
    for close_event_id, close_revision in new_closes:
        commits = trailer_commits[(close_event_id, close_revision)]
        if len(commits) != 1:
            raise StudyCloseDeliveryError(
                f"Study close {close_event_id} revision {close_revision} "
                "lacks one authenticated commit"
            )
        _validate_snapshot(root, commits[0], close_event_id, close_revision)
    close_count = body["prospective_close_count"]
    close_chain_digest = body["prospective_close_chain_digest"]
    for close_event_id, close_revision in new_closes:
        close_chain_digest = _advance_close_chain(
            close_chain_digest, close_event_id, close_revision
        )
        close_count += 1
    _best_effort_write_cache(
        root,
        _cache_body(
            main_head=main_head,
            repair_manifest_digest=body["repair_manifest_digest"],
            cursor=next_cursor,
            close_count=close_count,
            close_chain_digest=close_chain_digest,
        ),
    )


__all__ = [
    "BASE_REQUIRED_PATHS",
    "CHECKPOINT_PATH",
    "REQUIRED_PATHS",
    "StudyCloseCheckpointPlan",
    "StudyCloseDeliveryError",
    "StudyCloseGuardCapability",
    "audit_all_study_close_deliveries",
    "check_study_close_delivery_checkpoint",
    "check_study_close_delivery_checkpoint_maintenance",
    "check_study_close_delivery_checkpoint_v2_upgrade",
    "initialize_study_close_delivery_checkpoint",
    "prepare_study_close_delivery_checkpoint",
    "prepare_study_close_delivery_checkpoint_maintenance",
    "prepare_study_close_delivery_checkpoint_v2_upgrade",
    "render_projection",
    "require_all_study_close_deliveries",
    "inspect_tracked_study_close_delivery",
    "require_local_main",
    "require_study_close_guard_ready",
    "validate_commit_message",
]
