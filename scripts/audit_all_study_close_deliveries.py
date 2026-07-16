from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from axiom_rift.operations.study_close_git import (  # noqa: E402
    CHECKPOINT_PATH,
    KPI_PATH,
    StudyCloseDeliveryError,
    audit_all_study_close_deliveries,
    check_study_close_delivery_checkpoint_maintenance,
    check_study_close_delivery_checkpoint_v2_upgrade,
    initialize_study_close_delivery_checkpoint,
    prepare_study_close_delivery_checkpoint_v2_upgrade,
    prepare_study_close_delivery_checkpoint_maintenance,
    require_all_study_close_deliveries,
    require_study_close_guard_ready,
)
from axiom_rift.operations.writer import StateWriter  # noqa: E402


def _emit(value: object, *, stream: object = sys.stdout) -> None:
    print(
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
        file=stream,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the fast tracked-checkpoint guard by default. Complete-history "
            "and legacy-cache maintenance require --full-maintenance."
        )
    )
    parser.add_argument(
        "--full-maintenance",
        action="store_true",
        help="explicitly audit complete Git and Journal history",
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--initialize-checkpoint",
        action="store_true",
        help="write the first tracked v2 checkpoint after full maintenance",
    )
    actions.add_argument(
        "--upgrade-checkpoint-v2",
        action="store_true",
        help="project the existing v1 checkpoint into one explicit v2 milestone",
    )
    actions.add_argument(
        "--advance-no-close-checkpoint",
        action="store_true",
        help="advance the v2 Journal cursor after explicit full maintenance",
    )
    actions.add_argument(
        "--materialize-kpi-navigation",
        action="store_true",
        help=(
            "explicitly rebuild and stage the lag-tolerant KPI Markdown plus its "
            "maintenance checkpoint"
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="with a checkpoint action, validate without writing",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if (
        (
            arguments.initialize_checkpoint
            or arguments.upgrade_checkpoint_v2
            or arguments.advance_no_close_checkpoint
            or arguments.materialize_kpi_navigation
        )
        and not arguments.full_maintenance
    ):
        _emit(
            {
                "error": {
                    "code": "full_maintenance_required",
                    "message": (
                        "checkpoint initialization or v2 upgrade requires "
                        "--full-maintenance"
                    ),
                    "next_command": (
                        "python scripts/audit_all_study_close_deliveries.py "
                        "--full-maintenance --upgrade-checkpoint-v2 --check"
                    ),
                },
                "schema": "study_close_audit_cli_error.v1",
            },
            stream=sys.stderr,
        )
        return 2
    if arguments.check and not (
        arguments.upgrade_checkpoint_v2
        or arguments.advance_no_close_checkpoint
        or arguments.materialize_kpi_navigation
    ):
        _emit(
            {
                "error": {
                    "code": "check_action_required",
                    "message": "--check requires an explicit checkpoint action",
                    "next_command": (
                        "python scripts/audit_all_study_close_deliveries.py "
                        "--full-maintenance --upgrade-checkpoint-v2 --check"
                    ),
                },
                "schema": "study_close_audit_cli_error.v1",
            },
            stream=sys.stderr,
        )
        return 2
    if arguments.check and arguments.materialize_kpi_navigation:
        _emit(
            {
                "error": {
                    "code": "materialization_writes_required",
                    "message": "KPI navigation materialization cannot run in --check mode",
                    "next_command": (
                        "python scripts/audit_all_study_close_deliveries.py "
                        "--full-maintenance --materialize-kpi-navigation"
                    ),
                },
                "schema": "study_close_audit_cli_error.v1",
            },
            stream=sys.stderr,
        )
        return 2
    checkpoint = None
    mode = "tracked_checkpoint"
    projection_changed = False
    try:
        require_study_close_guard_ready(ROOT)
        if arguments.initialize_checkpoint:
            checkpoint = initialize_study_close_delivery_checkpoint(ROOT)
            mode = "initialize_checkpoint_v2"
        elif arguments.upgrade_checkpoint_v2:
            checkpoint = (
                check_study_close_delivery_checkpoint_v2_upgrade(ROOT)
                if arguments.check
                else prepare_study_close_delivery_checkpoint_v2_upgrade(ROOT)
            )
            mode = "check_checkpoint_v2_upgrade" if arguments.check else "write_checkpoint_v2_upgrade"
        elif arguments.advance_no_close_checkpoint:
            checkpoint = (
                check_study_close_delivery_checkpoint_maintenance(ROOT)
                if arguments.check
                else prepare_study_close_delivery_checkpoint_maintenance(ROOT)
            )
            mode = (
                "check_no_close_checkpoint_maintenance"
                if arguments.check
                else "write_no_close_checkpoint_maintenance"
            )
        elif arguments.materialize_kpi_navigation:
            staged = subprocess.run(
                ("git", "diff", "--cached", "--name-only"),
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.splitlines()
            if staged:
                raise StudyCloseDeliveryError(
                    "KPI navigation maintenance requires an empty staged set"
                )
            writer = StateWriter(ROOT)
            projection_changed = writer.rebuild_study_kpi_projection()
            if projection_changed:
                subprocess.run(
                    ("git", "add", "--", KPI_PATH),
                    cwd=ROOT,
                    check=True,
                    capture_output=True,
                )
            try:
                checkpoint = prepare_study_close_delivery_checkpoint_maintenance(
                    ROOT
                )
            except StudyCloseDeliveryError as exc:
                if projection_changed or "did not advance" not in str(exc):
                    raise
                mode = "kpi_navigation_already_current"
            else:
                subprocess.run(
                    ("git", "add", "--", CHECKPOINT_PATH),
                    cwd=ROOT,
                    check=True,
                    capture_output=True,
                )
                mode = "materialize_kpi_navigation"
        elif arguments.full_maintenance:
            audit_all_study_close_deliveries(ROOT)
            mode = "full_maintenance"
        else:
            require_all_study_close_deliveries(ROOT)
    except (OSError, subprocess.CalledProcessError, StudyCloseDeliveryError) as exc:
        _emit(
            {
                "error": {
                    "code": "study_close_delivery_invalid",
                    "message": str(exc),
                    "next_command": "git status --short",
                },
                "schema": "study_close_audit_cli_error.v1",
            },
            stream=sys.stderr,
        )
        return 1
    result: dict[str, object] = {
        "mode": mode,
        "projection_changed": projection_changed,
        "schema": "study_close_audit_cli_result.v1",
        "status": "valid",
    }
    if checkpoint is not None:
        result.update(
            {
                "checkpoint_digest": checkpoint.checkpoint_digest,
                "checkpoint_schema": checkpoint.schema,
                "next_command": (
                    "no_write"
                    if arguments.check
                    else (
                        "git diff --cached --name-only"
                        if arguments.materialize_kpi_navigation
                        else f"git add -- {CHECKPOINT_PATH}"
                    )
                ),
                "trailers": [
                    "Axiom-Study-Close-Checkpoint: "
                    f"{checkpoint.checkpoint_digest}",
                    f"Axiom-State-Revision: {checkpoint.cursor.sequence}",
                ],
            }
        )
    _emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
