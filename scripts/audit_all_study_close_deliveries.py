from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from axiom_rift.operations.study_close_git import (  # noqa: E402
    require_all_study_close_deliveries,
    require_study_close_guard_ready,
)


if __name__ == "__main__":
    require_study_close_guard_ready(ROOT)
    require_all_study_close_deliveries(ROOT)
    print("Study-close delivery audit: valid")
