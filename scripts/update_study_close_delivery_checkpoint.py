#!/usr/bin/env python3
"""Render the tracked checkpoint for one already-staged Study close."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from axiom_rift.operations.study_close_git import (  # noqa: E402
    prepare_study_close_delivery_checkpoint,
    require_study_close_guard_ready,
)


if __name__ == "__main__":
    require_study_close_guard_ready(ROOT)
    checkpoint = prepare_study_close_delivery_checkpoint(ROOT)
    print("Study-close delivery checkpoint written; stage it with the close.")
    print(f"Axiom-Study-Close: {checkpoint.last_study_close_event_id}")
    print(f"Axiom-State-Revision: {checkpoint.last_study_close_revision}")
