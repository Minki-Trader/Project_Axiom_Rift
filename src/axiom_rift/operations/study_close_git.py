"""Git delivery guard for legacy and segmented Study-close checkpoints."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Sequence

from axiom_rift.storage.journal import (
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
BASE_REQUIRED_PATHS = (CONTROL_PATH, KPI_PATH)
# Kept as the exact legacy checkpoint surface for compatibility callers.
REQUIRED_PATHS = (CONTROL_PATH, LEGACY_JOURNAL_RELATIVE_PATH, KPI_PATH)
COMMIT_MSG_HOOK_PATH = ".githooks/commit-msg"
COMMIT_MSG_HOOK = (
    b'#!/bin/sh\nexec python scripts/validate_study_close_commit.py "$1"\n'
)
_DIGEST = r"[0-9a-f]{64}"


class StudyCloseDeliveryError(RuntimeError):
    """A Study-close Git checkpoint is absent or malformed."""


def require_study_close_guard_ready(repository_root: str | Path) -> None:
    """Fail closed unless the tracked Study-close commit trigger is active."""

    root = Path(repository_root).resolve()
    if not (root / ".git").exists():
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


def _journal_paths_from_git(root: Path, *arguments: str) -> tuple[str, ...]:
    try:
        output = str(_git(root, *arguments))
    except subprocess.CalledProcessError:
        return ()
    return tuple(path for path in output.splitlines() if path)


def _worktree_journal(root: Path) -> JournalSnapshot:
    def load(path: str) -> bytes | None:
        candidate = root / Path(path)
        return candidate.read_bytes() if candidate.is_file() else None

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
    return read_journal_snapshot(load, listed_paths=paths)


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
    message = Path(message_path).read_text(encoding="utf-8")
    _validate_trailers(message, event_id, revision)


def _prospective_closes(events: Sequence[Mapping[str, Any]]) -> list[tuple[str, int]]:
    result: list[tuple[str, int]] = []
    for event in events:
        if any(
            record.get("kind") == "study-kpi"
            and record.get("payload", {}).get("provenance") == "prospective_close"
            for record in event.get("index_records", [])
        ):
            result.append((event["event_id"], event["sequence"]))
    return result


def _trailer_commits(root: Path) -> dict[tuple[str, int], list[str]]:
    output = str(_git(root, "log", "main", "--format=%H%x1f%B%x1e"))
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


def require_all_study_close_deliveries(repository_root: str | Path) -> None:
    root = Path(repository_root).resolve()
    if not (root / ".git").exists():
        return
    try:
        events = _events(_worktree_journal(root))
    except (OSError, JournalIntegrityError) as exc:
        raise StudyCloseDeliveryError("worktree Journal audit failed") from exc
    trailer_commits = _trailer_commits(root)
    repair_path = root / "records" / "STUDY_CLOSE_DELIVERY_REPAIR.json"
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


__all__ = [
    "BASE_REQUIRED_PATHS",
    "REQUIRED_PATHS",
    "StudyCloseDeliveryError",
    "render_projection",
    "require_all_study_close_deliveries",
    "require_study_close_guard_ready",
    "validate_commit_message",
]
