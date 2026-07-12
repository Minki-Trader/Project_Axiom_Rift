from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from axiom_rift.operations.study_close_git import (  # noqa: E402
    StudyCloseDeliveryError,
    validate_commit_message,
)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_study_close_commit.py COMMIT_MESSAGE", file=sys.stderr)
        return 2
    try:
        validate_commit_message(ROOT, sys.argv[1])
    except (OSError, RuntimeError, StudyCloseDeliveryError) as exc:
        print(f"Study-close commit rejected: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
