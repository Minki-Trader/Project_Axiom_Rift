from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from axiom_rift.operations.study_close_git import (  # noqa: E402
    require_all_study_close_deliveries,
    require_study_close_guard_ready,
)
from axiom_rift.operations.writer import StateWriter  # noqa: E402


OPERATION_ID = "journal-storage-segmentation-v1"
CONTRACT_OPERATION_ID = "journal-segmentation-operations-contract-v1"


def git(*arguments: str) -> str:
    result = subprocess.run(
        ("git", *arguments),
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return result.stdout.decode("ascii").strip()


def require_clean_main_boundary() -> None:
    if git("rev-parse", "--abbrev-ref", "HEAD") != "main":
        raise RuntimeError("Journal migration requires local main")
    head = git("rev-parse", "HEAD")
    if git("rev-parse", "main") != head:
        raise RuntimeError("Journal migration requires HEAD at local main")
    if git("rev-parse", "origin/main") != head:
        raise RuntimeError("Journal migration requires observed origin/main equality")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise RuntimeError("Journal migration requires a clean worktree")


def active_stable_allowed(control: dict[str, object]) -> bool:
    scientific = control.get("scientific")
    if not isinstance(scientific, dict):
        raise RuntimeError("control scientific state is malformed")
    return scientific.get("active_mission") is not None


def require_segmented_contract(content: bytes) -> None:
    try:
        value = yaml.safe_load(content.decode("ascii"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise RuntimeError("operations contract replacement is invalid") from exc
    durable = value.get("authority", {}).get("durable_journal", {})
    storage = value.get("journal_storage", {})
    if (
        not isinstance(durable, dict)
        or durable.get("segmented_manifest") != "records/journal/manifest.json"
        or storage.get("offset_mode") not in {None, "global_virtual"}
        or storage.get("sealed_segments_immutable") is not True
        or storage.get("segment_byte_limit") != 33_554_432
        or storage.get("segment_event_limit") != 5_000
    ):
        raise RuntimeError("operations contract does not bind segmented Journal storage")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Activate Axiom segmented Journal storage at a stable boundary."
    )
    parser.add_argument(
        "--operations-contract-source",
        type=Path,
        help=(
            "ASCII operations.yaml replacement to activate through the StateWriter "
            "before Journal migration"
        ),
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    require_clean_main_boundary()
    require_study_close_guard_ready(ROOT)
    require_all_study_close_deliveries(ROOT)

    writer = StateWriter(ROOT)
    before = writer.read_control()
    if before is None:
        raise RuntimeError("Journal migration requires initialized control")
    before = deepcopy(before)
    allow_active = active_stable_allowed(before)

    contract_source = arguments.operations_contract_source
    desired_contract = (
        None if contract_source is None else contract_source.resolve().read_bytes()
    )
    current_contract_path = ROOT / "contracts" / "operations.yaml"
    if desired_contract is not None:
        require_segmented_contract(desired_contract)
        if desired_contract != current_contract_path.read_bytes():
            writer.migrate_authority(
                replacements={"contracts/operations.yaml": desired_contract},
                reason="bind dual legacy and segmented Journal authority paths",
                operation_id=CONTRACT_OPERATION_ID,
                allow_active_stable_boundary=allow_active,
            )
    require_segmented_contract(current_contract_path.read_bytes())

    legacy_path = ROOT / "records" / "journal.jsonl"
    legacy_before = legacy_path.read_bytes()
    legacy_hash = sha256(legacy_before).hexdigest()
    legacy_events = writer.journal.read_all()
    result = writer.migrate_journal_storage(
        reason="preserve global Journal coordinates in immutable bounded segments",
        operation_id=OPERATION_ID,
        allow_active_stable_boundary=allow_active,
    )
    report = writer.recover()
    if report.get("study_kpi_projection_changed"):
        raise RuntimeError("Journal migration changed the Study KPI projection")
    after = writer.read_control()
    if after is None:
        raise RuntimeError("Journal migration lost control state")
    for field in ("scientific", "next_action", "initiative"):
        if after[field] != before[field]:
            raise RuntimeError(f"Journal migration changed control field {field}")
    if after["scientific"]["holdout_reveals"] != before["scientific"]["holdout_reveals"]:
        raise RuntimeError("Journal migration changed holdout accounting")
    events = writer.journal.read_all()
    if events[: len(legacy_events)] != legacy_events:
        raise RuntimeError("Journal migration changed a predecessor event")
    if events[-1]["event_kind"] != "journal_storage_migrated":
        raise RuntimeError("Journal storage migration event is not the tail")
    segment = ROOT / "records" / "journal" / "journal-000001.jsonl"
    if not segment.read_bytes().startswith(legacy_before):
        raise RuntimeError("sealed Journal segment changed the legacy byte prefix")
    if legacy_path.exists():
        raise RuntimeError("legacy Journal remains after segmented activation")
    manifest = json.loads(
        (ROOT / "records" / "journal" / "manifest.json").read_bytes()
    )
    allowed = {
        "contracts/operations.yaml",
        "records/journal.jsonl",
        "records/journal/manifest.json",
        "records/journal/journal-000001.jsonl",
        "records/journal/journal-000001.seal.json",
        "records/journal/journal-000002.jsonl",
        "state/control.json",
    }
    changed = {
        row[3:]
        for row in git("status", "--porcelain", "--untracked-files=all").splitlines()
        if row
    }
    if not changed.issubset(allowed):
        raise RuntimeError(f"Journal migration changed unrelated paths: {sorted(changed - allowed)}")
    print(
        json.dumps(
            {
                "active_segment": manifest["active_segment"]["path"],
                "event_id": result.event_id,
                "legacy_byte_length": len(legacy_before),
                "legacy_sha256": legacy_hash,
                "manifest_digest": manifest["manifest_digest"],
                "revision": result.revision,
                "sealed_segment_sha256": manifest["sealed_segments"][0]["sha256"],
                "status": "valid",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
