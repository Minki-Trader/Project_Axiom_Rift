#!/usr/bin/env python3
"""Check or render the checkpoint for one exactly staged Study close."""

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
    StudyCloseDeliveryError,
    attempt_study_close_origin_delivery,
    check_study_close_delivery_checkpoint,
    prepare_study_close_delivery_checkpoint,
    require_study_close_guard_ready,
)


LOCAL_GIT_TIMEOUT_SECONDS = 2 * 60


def _emit(value: object, *, stream: object = sys.stdout) -> None:
    print(
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
        file=stream,
    )


def _error_payload(exc: BaseException) -> dict[str, object]:
    message = str(exc)
    code = "checkpoint_preflight_failed"
    next_command = "git status --short"
    if "local main" in message:
        code = "local_main_required"
        next_command = "git switch main"
    elif "v2" in message and "upgrade" in message:
        code = "checkpoint_v2_upgrade_required"
        next_command = (
            "python scripts/audit_all_study_close_deliveries.py "
            "--full-maintenance --upgrade-checkpoint-v2 --check"
        )
    elif "exact staging" in message or "staged Journal" in message:
        code = "exact_staging_required"
        next_command = "git diff --cached --name-only"
    return {
        "error": {
            "code": code,
            "message": message,
            "next_command": next_command,
        },
        "schema": "study_close_checkpoint_cli_error.v1",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate exact Study-close staging and render checkpoint v2. "
            "The command never stages arbitrary paths."
        )
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="run the complete preflight without writing the checkpoint",
    )
    parser.add_argument(
        "--allow-milestone-path",
        action="append",
        default=[],
        metavar="PATH",
        help=(
            "explicit Study-scoped non-projection path already staged with the "
            "milestone; repeat for each path"
        ),
    )
    parser.add_argument(
        "--stage-checkpoint",
        action="store_true",
        help=(
            "after a successful render, stage only "
            "records/STUDY_CLOSE_DELIVERY_CHECKPOINT.json"
        ),
    )
    parser.add_argument(
        "--attempt-origin",
        action="store_true",
        help=(
            "after the checkpoint commit exists, perform the one bounded "
            "origin fetch/push attempt and retain its local receipt"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.attempt_origin and (
        arguments.check
        or arguments.stage_checkpoint
        or arguments.allow_milestone_path
    ):
        _emit(
            {
                "error": {
                    "code": "conflicting_actions",
                    "message": (
                        "--attempt-origin is a standalone post-commit action"
                    ),
                    "next_command": (
                        "python scripts/update_study_close_delivery_checkpoint.py "
                        "--attempt-origin"
                    ),
                },
                "schema": "study_close_checkpoint_cli_error.v1",
            },
            stream=sys.stderr,
        )
        return 2
    if arguments.check and arguments.stage_checkpoint:
        _emit(
            {
                "error": {
                    "code": "conflicting_actions",
                    "message": "--check cannot be combined with --stage-checkpoint",
                    "next_command": "python scripts/update_study_close_delivery_checkpoint.py --help",
                },
                "schema": "study_close_checkpoint_cli_error.v1",
            },
            stream=sys.stderr,
        )
        return 2
    if arguments.attempt_origin:
        try:
            require_study_close_guard_ready(ROOT)
            attempt_study_close_origin_delivery(ROOT)
        except (
            OSError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            StudyCloseDeliveryError,
        ) as exc:
            _emit(_error_payload(exc), stream=sys.stderr)
            return 1
        _emit(
            {
                "mode": "attempt_origin",
                "next_command": "git status --short",
                "schema": "study_close_checkpoint_cli_result.v1",
            }
        )
        return 0

    allowed = tuple(sorted(set(arguments.allow_milestone_path)))
    try:
        require_study_close_guard_ready(ROOT)
        plan = check_study_close_delivery_checkpoint(
            ROOT, allowed_milestone_paths=allowed
        )
        checkpoint = plan.checkpoint
        if not arguments.check:
            checkpoint = prepare_study_close_delivery_checkpoint(
                ROOT, allowed_milestone_paths=allowed
            )
            if arguments.stage_checkpoint:
                subprocess.run(
                    ("git", "add", "--", CHECKPOINT_PATH),
                    cwd=ROOT,
                    check=True,
                    capture_output=True,
                    timeout=LOCAL_GIT_TIMEOUT_SECONDS,
                )
    except (
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        StudyCloseDeliveryError,
    ) as exc:
        _emit(_error_payload(exc), stream=sys.stderr)
        return 1
    next_command = (
        "python scripts/update_study_close_delivery_checkpoint.py"
        if arguments.check
        else (
            "git diff --cached --name-only"
            if arguments.stage_checkpoint
            else f"git add -- {CHECKPOINT_PATH}"
        )
    )
    _emit(
        {
            "allowed_milestone_paths": list(plan.allowed_milestone_paths),
            "checkpoint_digest": checkpoint.checkpoint_digest,
            "last_study_close_event_id": checkpoint.last_study_close_event_id,
            "last_study_close_revision": checkpoint.last_study_close_revision,
            "mode": "check" if arguments.check else "write",
            "next_command": next_command,
            "required_staged_paths": list(plan.required_staged_paths),
            "schema": "study_close_checkpoint_cli_result.v1",
            "trailers": [
                f"Axiom-Study-Close: {checkpoint.last_study_close_event_id}",
                f"Axiom-State-Revision: {checkpoint.last_study_close_revision}",
            ],
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
