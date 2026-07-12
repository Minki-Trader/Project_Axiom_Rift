"""Git delivery guard for prospective Study close checkpoints."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Sequence

from axiom_rift.storage.study_kpi import StudyKpiProjectionRow, render_study_kpi


REQUIRED_PATHS = (
    "state/control.json",
    "records/journal.jsonl",
    "records/STUDY_KPI.md",
)
_DIGEST = r"[0-9a-f]{64}"


class StudyCloseDeliveryError(RuntimeError):
    """A Study-close Git checkpoint is absent or malformed."""


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


def _events(content: bytes) -> list[dict[str, Any]]:
    return [json.loads(line) for line in content.decode("ascii").splitlines()]


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


def validate_commit_message(repository_root: str | Path, message_path: str | Path) -> None:
    root = Path(repository_root).resolve()
    staged_text = _git(root, "diff", "--cached", "--name-only")
    unstaged_text = _git(root, "diff", "--name-only")
    staged = set(str(staged_text).splitlines())
    unstaged = set(str(unstaged_text).splitlines())
    journal = root / "records" / "journal.jsonl"
    pending_close = False
    if journal.is_file():
        worktree_events = _events(journal.read_bytes())
        pending_close = (
            worktree_events[-1]["event_kind"] == "study_closed"
            and bool((staged | unstaged) & set(REQUIRED_PATHS))
        )
    if not pending_close and "records/journal.jsonl" not in staged:
        return
    try:
        staged_journal = _git(
            root, "show", ":records/journal.jsonl", binary=True
        )
    except subprocess.CalledProcessError:
        if pending_close:
            raise StudyCloseDeliveryError(
                "pending Study close requires all projection paths staged"
            ) from None
        return
    assert isinstance(staged_journal, bytes)
    staged_events = _events(staged_journal)
    if staged_events[-1]["event_kind"] != "study_closed":
        if pending_close:
            raise StudyCloseDeliveryError(
                "pending Study close cannot be split across commits"
            )
        return
    if not set(REQUIRED_PATHS).issubset(staged) or set(REQUIRED_PATHS) & unstaged:
        raise StudyCloseDeliveryError(
            "Study close requires state, Journal, and KPI staged together"
        )
    staged_control = _git(root, "show", ":state/control.json", binary=True)
    staged_kpi = _git(root, "show", ":records/STUDY_KPI.md", binary=True)
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
    output = str(
        _git(
            root,
            "log",
            "main",
            "--format=%H%x1f%B%x1e",
        )
    )
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
    if not set(REQUIRED_PATHS).issubset(changed):
        raise StudyCloseDeliveryError("Study-close commit split required paths")
    events = _events(_snapshot(root, commit, "records/journal.jsonl"))
    control = json.loads(_snapshot(root, commit, "state/control.json"))
    observed_event, observed_revision = _validate_boundary(
        control=control, events=events
    )
    if observed_event != event_id or observed_revision != revision:
        raise StudyCloseDeliveryError("Study-close commit snapshot differs")
    if _snapshot(root, commit, "records/STUDY_KPI.md") != render_projection(events):
        raise StudyCloseDeliveryError("Study-close commit KPI differs")


def require_all_study_close_deliveries(repository_root: str | Path) -> None:
    root = Path(repository_root).resolve()
    if not (root / ".git").exists():
        return
    events = _events((root / "records" / "journal.jsonl").read_bytes())
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
    for event_id, revision in _prospective_closes(events):
        commits = trailer_commits.get((event_id, revision), [])
        if len(commits) == 1:
            _validate_snapshot(root, commits[0], event_id, revision)
            continue
        repaired_commit = repaired.get((event_id, revision))
        if len(commits) == 0 and repaired_commit is not None:
            _validate_snapshot(root, repaired_commit, event_id, revision)
            continue
        raise StudyCloseDeliveryError(
            f"Study close {event_id} revision {revision} lacks one authenticated commit"
        )


__all__ = [
    "StudyCloseDeliveryError",
    "require_all_study_close_deliveries",
    "validate_commit_message",
]
