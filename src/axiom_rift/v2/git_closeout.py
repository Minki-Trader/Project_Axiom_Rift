"""Safe, scoped V2 Git closeout with no history-rewriting behavior."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


@dataclass(frozen=True)
class GitBlocker:
    code: str
    root_cause: str
    reproduction_command: str
    affected_paths: tuple[str, ...]
    next_action: str
    external_state_required: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "root_cause": self.root_cause,
            "reproduction_command": self.reproduction_command,
            "affected_paths": list(self.affected_paths),
            "next_action": self.next_action,
            "external_state_required": self.external_state_required,
        }


@dataclass(frozen=True)
class GitPreflightResult:
    ok: bool
    root: str
    branch: str | None
    head: str | None
    remote_head: str | None
    declared_paths: tuple[str, ...]
    unrelated_dirty_paths: tuple[str, ...]
    blocker: GitBlocker | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema": "axiom_rift_v21_git_preflight_v1",
            "ok": self.ok,
            "root": self.root,
            "branch": self.branch,
            "head": self.head,
            "remote_head": self.remote_head,
            "declared_paths": list(self.declared_paths),
            "unrelated_dirty_paths": list(self.unrelated_dirty_paths),
            "blocker": self.blocker.to_payload() if self.blocker else None,
        }


@dataclass(frozen=True)
class GitCloseoutResult:
    status: str
    branch: str
    push_target: str
    head: str | None
    remote_head: str | None
    commit_created: bool
    push_attempts: int
    declared_paths: tuple[str, ...]
    blocker: GitBlocker | None = None

    @property
    def ok(self) -> bool:
        return self.status == "complete" and self.blocker is None

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema": "axiom_rift_v21_git_closeout_v1",
            "status": self.status,
            "ok": self.ok,
            "branch": self.branch,
            "push_target": self.push_target,
            "head": self.head,
            "remote_head": self.remote_head,
            "commit_created": self.commit_created,
            "push_attempts": self.push_attempts,
            "declared_paths": list(self.declared_paths),
            "blocker": self.blocker.to_payload() if self.blocker else None,
        }


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    command = ["git", *args]
    try:
        return subprocess.run(
            command,
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            command,
            124,
            stdout=exc.stdout or "",
            stderr=f"git command exceeded 30 seconds: {' '.join(command)}",
        )


def _detail(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout or f"git exited {result.returncode}").strip()


def _normalize_declared_paths(root: Path, paths: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw in paths:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("declared Git paths must be nonempty strings")
        candidate = raw.replace("\\", "/")
        pure = PurePosixPath(candidate)
        if pure.is_absolute() or ".." in pure.parts or ".git" in pure.parts:
            raise ValueError(f"unsafe declared Git path: {raw}")
        relative = pure.as_posix()
        if not relative or relative == ".":
            raise ValueError("repository root cannot be a declared Git path")
        resolved = (root / relative).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"declared Git path escapes the repository: {raw}") from exc
        if relative not in normalized:
            normalized.append(relative)
    if not normalized:
        raise ValueError("at least one declared Git path is required")
    return tuple(normalized)


def _covered(path: str, declared_paths: tuple[str, ...]) -> bool:
    normalized = path.replace("\\", "/")
    return any(normalized == declared or normalized.startswith(declared.rstrip("/") + "/") for declared in declared_paths)


def _name_lines(result: subprocess.CompletedProcess[str]) -> tuple[str, ...]:
    return tuple(line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip())


def _dirty_paths(root: Path) -> tuple[str, ...]:
    result = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    if result.returncode != 0:
        raise RuntimeError(_detail(result))
    paths: list[str] = []
    for line in result.stdout.splitlines():
        value = line[3:]
        if " -> " in value:
            value = value.split(" -> ", 1)[1]
        value = value.strip().strip('"').replace("\\", "/")
        if value and value not in paths:
            paths.append(value)
    return tuple(paths)


def _remote_head(root: Path) -> str | None:
    result = _git(root, "ls-remote", "--heads", "origin", "refs/heads/main")
    if result.returncode != 0:
        raise RuntimeError(_detail(result))
    line = next((item for item in result.stdout.splitlines() if item.strip()), None)
    return line.split()[0] if line else None


def _blocker(
    code: str,
    cause: str,
    command: str,
    declared_paths: tuple[str, ...],
    next_action: str,
    external: str | None = None,
) -> GitBlocker:
    return GitBlocker(code, cause, command, declared_paths, next_action, external)


def git_preflight(root: Path, declared_paths: Iterable[str]) -> GitPreflightResult:
    """Read-only preflight; never merge, rebase, reset, checkout, or force."""

    root = root.resolve()
    try:
        declared = _normalize_declared_paths(root, declared_paths)
    except ValueError as exc:
        blocker = _blocker("unsafe_declared_path", str(exc), "git status --short", (), "declare repository-relative paths only")
        return GitPreflightResult(False, root.as_posix(), None, None, None, (), (), blocker)
    top = _git(root, "rev-parse", "--show-toplevel")
    if top.returncode != 0 or Path(top.stdout.strip()).resolve() != root:
        blocker = _blocker("not_repository_root", _detail(top), "git rev-parse --show-toplevel", declared, "run closeout from the exact repository root")
        return GitPreflightResult(False, root.as_posix(), None, None, None, declared, (), blocker)
    branch_result = _git(root, "branch", "--show-current")
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else None
    if branch != "main":
        blocker = _blocker("branch_not_main", f"current branch is {branch!r}", "git branch --show-current", declared, "switch to main explicitly before closeout")
        return GitPreflightResult(False, root.as_posix(), branch, None, None, declared, (), blocker)
    remote = _git(root, "remote", "get-url", "origin")
    if remote.returncode != 0:
        blocker = _blocker("origin_missing", _detail(remote), "git remote get-url origin", declared, "configure origin explicitly")
        return GitPreflightResult(False, root.as_posix(), branch, None, None, declared, (), blocker)
    fetch = _git(root, "fetch", "origin", "main")
    if fetch.returncode != 0:
        blocker = _blocker("origin_fetch_failed", _detail(fetch), "git fetch origin main", declared, "restore read access to origin/main", "remote_or_auth_state")
        return GitPreflightResult(False, root.as_posix(), branch, None, None, declared, (), blocker)
    head_result = _git(root, "rev-parse", "HEAD")
    head = head_result.stdout.strip() if head_result.returncode == 0 else None
    try:
        remote_head = _remote_head(root)
    except RuntimeError as exc:
        blocker = _blocker("remote_head_unavailable", str(exc), "git ls-remote --heads origin refs/heads/main", declared, "restore remote visibility", "remote_or_auth_state")
        return GitPreflightResult(False, root.as_posix(), branch, head, None, declared, (), blocker)
    if not head or not remote_head:
        blocker = _blocker("head_missing", "local HEAD or origin/main is missing", "git rev-parse HEAD", declared, "establish main and origin/main explicitly")
        return GitPreflightResult(False, root.as_posix(), branch, head, remote_head, declared, (), blocker)
    ancestor = _git(root, "merge-base", "--is-ancestor", remote_head, head)
    if ancestor.returncode != 0:
        blocker = _blocker(
            "remote_not_ancestor",
            "local main does not contain origin/main; automatic merge or rebase is forbidden",
            "git merge-base --is-ancestor origin/main HEAD",
            declared,
            "resolve branch divergence explicitly outside closeout",
        )
        return GitPreflightResult(False, root.as_posix(), branch, head, remote_head, declared, (), blocker)
    staged_result = _git(root, "diff", "--cached", "--name-only")
    if staged_result.returncode != 0:
        blocker = _blocker("staged_scan_failed", _detail(staged_result), "git diff --cached --name-only", declared, "inspect the index explicitly")
        return GitPreflightResult(False, root.as_posix(), branch, head, remote_head, declared, (), blocker)
    staged = _name_lines(staged_result)
    outside_staged = tuple(path for path in staged if not _covered(path, declared))
    if outside_staged:
        blocker = _blocker(
            "unscoped_staged_paths",
            "the index contains paths outside the declared closeout scope: " + ", ".join(outside_staged),
            "git diff --cached --name-only",
            declared,
            "unstage unrelated paths explicitly without discarding their work",
        )
        return GitPreflightResult(False, root.as_posix(), branch, head, remote_head, declared, (), blocker)
    try:
        dirty = _dirty_paths(root)
    except RuntimeError as exc:
        blocker = _blocker("status_failed", str(exc), "git status --porcelain=v1", declared, "inspect repository status")
        return GitPreflightResult(False, root.as_posix(), branch, head, remote_head, declared, (), blocker)
    unrelated = tuple(path for path in dirty if not _covered(path, declared))
    return GitPreflightResult(True, root.as_posix(), branch, head, remote_head, declared, unrelated)


def _blocked_closeout(preflight: GitPreflightResult) -> GitCloseoutResult:
    return GitCloseoutResult(
        status="blocked",
        branch=preflight.branch or "unknown",
        push_target="origin/main",
        head=preflight.head,
        remote_head=preflight.remote_head,
        commit_created=False,
        push_attempts=0,
        declared_paths=preflight.declared_paths,
        blocker=preflight.blocker,
    )


def scoped_git_closeout(
    root: Path,
    declared_paths: Iterable[str],
    commit_message: str,
    *,
    diagnostic_retry: bool = True,
) -> GitCloseoutResult:
    """Commit only declared paths, push main, then prove HEAD equals origin/main."""

    preflight = git_preflight(root, declared_paths)
    if not preflight.ok:
        return _blocked_closeout(preflight)
    root = root.resolve()
    declared = preflight.declared_paths
    if not commit_message.strip() or "\n" in commit_message or "\r" in commit_message:
        blocker = _blocker("invalid_commit_message", "commit message must be one nonempty line", "git commit -m <message>", declared, "provide one scoped commit message")
        return GitCloseoutResult("blocked", "main", "origin/main", preflight.head, preflight.remote_head, False, 0, declared, blocker)

    add = _git(root, "add", "--", *declared)
    if add.returncode != 0:
        blocker = _blocker("scoped_stage_failed", _detail(add), "git add -- <declared-paths>", declared, "repair the declared pathspec and retry with a new closeout operation")
        return GitCloseoutResult("blocked", "main", "origin/main", preflight.head, preflight.remote_head, False, 0, declared, blocker)
    staged_result = _git(root, "diff", "--cached", "--name-only")
    staged = _name_lines(staged_result) if staged_result.returncode == 0 else ()
    outside = tuple(path for path in staged if not _covered(path, declared))
    if staged_result.returncode != 0 or outside:
        cause = _detail(staged_result) if staged_result.returncode != 0 else "staged paths escaped declared scope: " + ", ".join(outside)
        blocker = _blocker("staged_scope_violation", cause, "git diff --cached --name-only", declared, "inspect and correct the index explicitly")
        return GitCloseoutResult("blocked", "main", "origin/main", preflight.head, preflight.remote_head, False, 0, declared, blocker)
    commit_created = bool(staged)
    if commit_created:
        commit = _git(root, "commit", "-m", commit_message)
        if commit.returncode != 0:
            blocker = _blocker("commit_failed", _detail(commit), "git commit -m <message>", declared, "repair the scoped commit failure without resetting work")
            return GitCloseoutResult("blocked", "main", "origin/main", preflight.head, preflight.remote_head, False, 0, declared, blocker)
    head_result = _git(root, "rev-parse", "HEAD")
    head = head_result.stdout.strip() if head_result.returncode == 0 else None
    if not head:
        blocker = _blocker("head_unavailable", _detail(head_result), "git rev-parse HEAD", declared, "restore local repository integrity")
        return GitCloseoutResult("blocked", "main", "origin/main", None, preflight.remote_head, commit_created, 0, declared, blocker)

    push_attempts = 1
    push = _git(root, "push", "origin", "HEAD:refs/heads/main")
    if push.returncode != 0 and diagnostic_retry:
        diagnostic = _git(root, "fetch", "origin", "main")
        retry_allowed = diagnostic.returncode == 0
        remote_after: str | None = None
        if retry_allowed:
            try:
                remote_after = _remote_head(root)
            except RuntimeError:
                retry_allowed = False
        if retry_allowed and remote_after is not None:
            ancestor = _git(root, "merge-base", "--is-ancestor", remote_after, head)
            retry_allowed = ancestor.returncode == 0
        if retry_allowed:
            push_attempts += 1
            push = _git(root, "push", "origin", "HEAD:refs/heads/main")
    if push.returncode != 0:
        blocker = _blocker(
            "push_failed",
            _detail(push),
            "git push origin HEAD:refs/heads/main",
            declared,
            "repair remote or authentication state, then resume the same closeout without force",
            "remote_or_auth_state",
        )
        try:
            observed_remote = _remote_head(root)
        except RuntimeError:
            observed_remote = None
        return GitCloseoutResult("blocked", "main", "origin/main", head, observed_remote, commit_created, push_attempts, declared, blocker)
    try:
        remote_head = _remote_head(root)
    except RuntimeError as exc:
        blocker = _blocker("push_verification_failed", str(exc), "git ls-remote --heads origin refs/heads/main", declared, "restore remote visibility and verify the pushed commit", "remote_or_auth_state")
        return GitCloseoutResult("blocked", "main", "origin/main", head, None, commit_created, push_attempts, declared, blocker)
    if remote_head != head:
        blocker = _blocker(
            "remote_head_mismatch",
            f"local HEAD {head} differs from origin/main {remote_head}",
            "git ls-remote --heads origin refs/heads/main",
            declared,
            "inspect remote movement and reconcile explicitly without force",
            "remote_state_changed",
        )
        return GitCloseoutResult("blocked", "main", "origin/main", head, remote_head, commit_created, push_attempts, declared, blocker)
    return GitCloseoutResult("complete", "main", "origin/main", head, remote_head, commit_created, push_attempts, declared)
