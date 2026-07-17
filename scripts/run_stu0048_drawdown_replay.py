"""Read-only compatibility handoff for the closed drawdown replay Study."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from axiom_rift.operations.fixed_hold_replay_cli import (  # noqa: E402
    run_fixed_hold_replay_command,
)
from axiom_rift.operations.writer import StateWriter  # noqa: E402
from axiom_rift.research.drawdown_state_replay_job import (  # noqa: E402
    execute_drawdown_state_replay_job,
    materialize_drawdown_replay_job_implementation,
)


STUDY_ID = "STU-0107"


def _closed_design(_writer: StateWriter):
    raise RuntimeError("closed historical runner has no prospective design authority")


def main(argv: Sequence[str] | None = None) -> None:
    summary = run_fixed_hold_replay_command(
        repository_root=ROOT,
        design_builder=_closed_design,
        job_runner=execute_drawdown_state_replay_job,
        job_implementation_materializer=(
            materialize_drawdown_replay_job_implementation
        ),
        study_id=STUDY_ID,
        argv=argv,
    )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
