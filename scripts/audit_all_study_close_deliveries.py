from __future__ import annotations

from pathlib import Path
import argparse
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from axiom_rift.operations.study_close_git import (  # noqa: E402
    audit_all_study_close_deliveries,
    initialize_study_close_delivery_checkpoint,
    require_study_close_guard_ready,
)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--initialize-checkpoint",
        action="store_true",
        help="write the first tracked checkpoint after the full audit",
    )
    arguments = parser.parse_args()
    require_study_close_guard_ready(ROOT)
    if arguments.initialize_checkpoint:
        checkpoint = initialize_study_close_delivery_checkpoint(ROOT)
        print(
            "Checkpoint written; stage records/STUDY_CLOSE_DELIVERY_CHECKPOINT.json"
        )
        print(
            "Axiom-Study-Close-Checkpoint: "
            f"{checkpoint.checkpoint_digest}"
        )
        print(f"Axiom-State-Revision: {checkpoint.cursor.sequence}")
    else:
        audit_all_study_close_deliveries(ROOT)
    print("Study-close delivery audit: valid")
