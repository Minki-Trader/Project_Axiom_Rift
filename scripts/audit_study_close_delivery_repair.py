from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "records" / "STUDY_CLOSE_DELIVERY_REPAIR.json"
REQUIRED_PATHS = (
    "state/control.json",
    "records/journal.jsonl",
    "records/STUDY_KPI.md",
)


def git(*arguments: str, binary: bool = False) -> bytes | str:
    result = subprocess.run(
        ("git", *arguments),
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return result.stdout if binary else result.stdout.decode("ascii").strip()


def ancestor(commit: str, reference: str) -> None:
    subprocess.run(
        ("git", "merge-base", "--is-ancestor", commit, reference),
        cwd=ROOT,
        check=True,
        capture_output=True,
    )


def snapshot(commit: str, path: str) -> bytes:
    value = git("show", f"{commit}:{path}", binary=True)
    assert isinstance(value, bytes)
    return value


def journal_events(content: bytes) -> list[dict[str, Any]]:
    return [json.loads(line) for line in content.decode("ascii").splitlines()]


def render_projection(events: list[dict[str, Any]]) -> bytes:
    sys.path.insert(0, str(ROOT / "src"))
    from axiom_rift.storage.study_kpi import (  # noqa: PLC0415
        StudyKpiProjectionRow,
        render_study_kpi,
    )

    event_times = {event["event_id"]: event["occurred_at_utc"] for event in events}
    rows: list[StudyKpiProjectionRow] = []
    for event in events:
        for record in event.get("index_records", []):
            if record.get("kind") != "study-kpi":
                continue
            payload = record["payload"]
            provenance = payload["provenance"]
            closed_at = (
                event["occurred_at_utc"]
                if provenance == "prospective_close"
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


def audit_entry(entry: dict[str, Any]) -> None:
    commit = entry["original_commit"]
    ancestor(commit, "main")
    ancestor(commit, "origin/main")
    observed_tree = git("rev-parse", f"{commit}^{{tree}}")
    if observed_tree != entry["original_tree"]:
        raise RuntimeError(f"{entry['study_id']} tree differs")
    changed = set(git("diff-tree", "--no-commit-id", "--name-only", "-r", commit).splitlines())
    if not set(REQUIRED_PATHS).issubset(changed):
        raise RuntimeError(f"{entry['study_id']} required paths were not co-committed")
    blob_fields = {
        "state/control.json": "control_blob",
        "records/journal.jsonl": "journal_blob",
        "records/STUDY_KPI.md": "study_kpi_blob",
    }
    for path, field in blob_fields.items():
        if git("rev-parse", f"{commit}:{path}") != entry[field]:
            raise RuntimeError(f"{entry['study_id']} {path} blob differs")
    control = json.loads(snapshot(commit, "state/control.json"))
    events = journal_events(snapshot(commit, "records/journal.jsonl"))
    tail = events[-1]
    if (
        control["revision"] != entry["state_revision"]
        or control["heads"]["journal"]["event_id"]
        != entry["study_close_event_id"]
        or tail["sequence"] != entry["state_revision"]
        or tail["event_id"] != entry["study_close_event_id"]
        or tail["event_kind"] != "study_closed"
    ):
        raise RuntimeError(f"{entry['study_id']} close boundary differs")
    ledger = snapshot(commit, "records/STUDY_KPI.md")
    if ledger != render_projection(events):
        raise RuntimeError(f"{entry['study_id']} KPI projection differs")
    message = git("show", "-s", "--format=%B", commit)
    if "Axiom-Study-Close:" in message or "Axiom-State-Revision:" in message:
        raise RuntimeError(f"{entry['study_id']} is not a missing-trailer repair")


def main() -> None:
    content = MANIFEST.read_bytes()
    value = json.loads(content)
    if set(value) != {
        "authority_migration_event_id",
        "entries",
        "repair_scope",
        "schema",
    } or value["schema"] != "study_close_delivery_repair.v1":
        raise RuntimeError("delivery repair manifest schema differs")
    if value["repair_scope"] != (
        "prospective_study_close_commits_missing_only_required_trailers"
    ):
        raise RuntimeError("delivery repair scope differs")
    entries = value["entries"]
    if len(entries) != 4 or len({entry["original_commit"] for entry in entries}) != 4:
        raise RuntimeError("delivery repair entries differ")
    for entry in entries:
        audit_entry(entry)
    print(
        json.dumps(
            {
                "manifest_sha256": sha256(content).hexdigest(),
                "repaired_commit_count": len(entries),
                "status": "valid",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
