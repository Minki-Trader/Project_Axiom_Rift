from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from axiom_rift.operations.writer import (
    InjectedCrash,
    RecoveryRequired,
    StateWriter,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXED_NOW = "2026-07-16T00:00:00.000000Z"


def _append_crashed_event(
    writer: StateWriter,
    *,
    crash_after: str,
) -> dict[str, Any]:
    def prepare(current, _index):  # type: ignore[no-untyped-def]
        assert current is not None
        body = StateWriter._body(current)
        record = IndexRecord(
            kind="atomic-recovery-fixture",
            record_id=f"atomic-recovery-fixture:{crash_after}",
            subject="Mission:atomic-recovery-fixture",
            status="recorded",
            fingerprint=("a" if crash_after == "after_journal" else "b") * 64,
            payload={"crash_after": crash_after},
        )
        return body, [record], {"crash_after": crash_after}

    with pytest.raises(InjectedCrash):
        writer._commit(  # noqa: SLF001 - adversarial crash-boundary fixture
            event_kind="atomic_recovery_fixture_recorded",
            operation_id=f"atomic-recovery-{crash_after}",
            subject="Mission:atomic-recovery-fixture",
            payload={"crash_after": crash_after},
            prepare=prepare,
            crash_after=crash_after,
        )
    return dict(writer.journal.read_all()[-1])


def _recovery_arguments(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "expected_sequence": event["sequence"],
        "expected_event_id": event["event_id"],
        "expected_operation_id": event["operation_id"],
        "expected_previous_event_id": event["previous_event_id"],
    }


@pytest.mark.parametrize("crash_after", ("after_journal", "after_cursor"))
def test_atomic_exact_trailing_recovery_accepts_only_predecessor_projection(
    tmp_path: Path,
    crash_after: str,
) -> None:
    writer = StateWriter(
        tmp_path,
        clock=lambda: FIXED_NOW,
        engineering_fixture=True,
        foundation_root=REPO_ROOT,
    )
    writer.initialize_ready()
    event = _append_crashed_event(writer, crash_after=crash_after)
    arguments = _recovery_arguments(event)

    boundary = writer.require_exact_trailing_event_recovery_boundary(
        **arguments
    )
    assert boundary["schema"] == "exact_trailing_event_recovery_boundary.v1"
    assert boundary["control_position"] == (
        "predecessor" if crash_after == "after_journal" else "trailing_event"
    )

    report = writer.recover_exact_trailing_event(**arguments)
    assert report["recovery_boundary"] == boundary
    assert report["journal_sequence"] == event["sequence"]
    assert report["index_rebuilt"] is True
    stable = writer.require_stable_head()
    assert stable["journal_event_id"] == event["event_id"]


def test_atomic_exact_trailing_recovery_rejects_foreign_projection(
    tmp_path: Path,
) -> None:
    writer = StateWriter(
        tmp_path,
        clock=lambda: FIXED_NOW,
        engineering_fixture=True,
        foundation_root=REPO_ROOT,
    )
    writer.initialize_ready()
    event = _append_crashed_event(writer, crash_after="after_journal")
    arguments = _recovery_arguments(event)
    control_before = writer.control.path.read_bytes()

    with LocalIndex(writer.index_path) as index:
        index.put(
            IndexRecord(
                kind="foreign-projection",
                record_id="foreign-projection",
                subject="Mission:foreign",
                status="forged",
                fingerprint="f" * 64,
                payload={"authority": False},
            )
        )

    with pytest.raises(
        RecoveryRequired,
        match="exact predecessor projection",
    ):
        writer.recover_exact_trailing_event(**arguments)
    assert writer.control.path.read_bytes() == control_before
    assert writer.journal.read_all()[-1]["event_id"] == event["event_id"]
