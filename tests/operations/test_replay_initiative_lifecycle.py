from __future__ import annotations

from types import SimpleNamespace
import unittest

from axiom_rift.operations.replay_initiative_lifecycle import (
    ReplayInitiativeBindingPhase,
    ReplayInitiativeLifecycle,
    require_replay_initiative_binding,
)
from axiom_rift.operations.replay_workflow_recovery import (
    replay_initiative_binding_phase,
)


MISSION_ID = "MIS-FIXTURE"
INITIATIVE_ID = "INI-FIXTURE"
PREFIX = "fixture-replay-"


def _operation(
    event_kind: str,
    initiative_id: str = INITIATIVE_ID,
    *,
    sequence: int = 10,
):
    return SimpleNamespace(
        authority_event_id=f"{sequence:064x}",
        authority_sequence=sequence,
        payload={
            "event_kind": event_kind,
            "result": {"initiative_id": initiative_id},
        },
        status="success",
    )


def _index(
    records: dict[tuple[str, str], object],
    *,
    subject_status_records: tuple[object, ...] = (),
):
    def records_by_subject_status(subject: str, status: str):
        return tuple(
            record
            for record in subject_status_records
            if record.subject == subject and record.status == status
        )

    return SimpleNamespace(
        get=lambda kind, record_id: records.get((kind, record_id)),
        records_by_subject_status=records_by_subject_status,
        records_by_kind=lambda _kind: (_ for _ in ()).throw(
            AssertionError("replay lifecycle must not scan records by kind")
        ),
    )


def _control(active_initiative: str | None, *, sequence: int | None = None):
    return {
        "authorizations": (
            {}
            if active_initiative is None
            else {
                f"Initiative:{active_initiative}": {
                    "kind": "Initiative",
                    "subject_id": active_initiative,
                }
            }
        ),
        "scientific": {
            "active_initiative": active_initiative,
            "active_mission": MISSION_ID,
        },
        **(
            {}
            if sequence is None
            else {
                "heads": {
                    "journal": {
                        "event_id": f"{sequence:064x}",
                        "sequence": sequence,
                    }
                }
            }
        ),
    }


def _owner_close(sequence: int):
    return SimpleNamespace(
        authority_event_id=f"{sequence:064x}",
        authority_sequence=sequence,
        kind="initiative-close",
        payload={"outcome": "completed"},
        status="completed",
        subject=f"Initiative:{INITIATIVE_ID}",
    )


class ReplayInitiativeLifecycleTests(unittest.TestCase):
    def _require(
        self,
        *,
        control: dict,
        records: dict[tuple[str, str], object],
        lifecycle: ReplayInitiativeLifecycle,
    ) -> None:
        require_replay_initiative_binding(
            control=control,
            index=_index(records),
            lifecycle=lifecycle,
            mission_id=MISSION_ID,
            initiative_id=INITIATIVE_ID,
            operation_prefix=PREFIX,
        )

    def test_borrowed_mode_requires_existing_exact_authority_without_ownership_events(
        self,
    ) -> None:
        records = {
            ("initiative-open", INITIATIVE_ID): SimpleNamespace(
                status="open",
                subject=f"Initiative:{INITIATIVE_ID}",
            )
        }
        self._require(
            control=_control(INITIATIVE_ID),
            records=records,
            lifecycle=ReplayInitiativeLifecycle.BORROW_ACTIVE_INITIATIVE,
        )

        attacks = (
            (_control("INI-OTHER"), records),
            (
                {
                    **_control(INITIATIVE_ID),
                    "authorizations": {},
                },
                records,
            ),
            (
                _control(INITIATIVE_ID),
                {
                    **records,
                    (
                        "operation",
                        PREFIX + "open-initiative",
                    ): _operation("initiative_opened"),
                },
            ),
            (
                _control(INITIATIVE_ID),
                {
                    **records,
                    (
                        "operation",
                        PREFIX + "close-initiative",
                    ): _operation("initiative_closed"),
                },
            ),
        )
        for control, attacked_records in attacks:
            with self.subTest(control=control, records=attacked_records):
                with self.assertRaisesRegex(RuntimeError, "exact active Initiative"):
                    self._require(
                        control=control,
                        records=attacked_records,
                        lifecycle=(
                            ReplayInitiativeLifecycle.BORROW_ACTIVE_INITIATIVE
                        ),
                    )

    def test_owned_mode_accepts_only_empty_open_and_closed_exact_phases(self) -> None:
        lifecycle = ReplayInitiativeLifecycle.OWN_BOUNDED_INITIATIVE
        self._require(control=_control(None), records={}, lifecycle=lifecycle)

        open_records = {
            (
                "operation",
                PREFIX + "open-initiative",
            ): _operation("initiative_opened")
        }
        self._require(
            control=_control(INITIATIVE_ID),
            records=open_records,
            lifecycle=lifecycle,
        )

        closed_records = {
            **open_records,
            (
                "operation",
                PREFIX + "close-initiative",
            ): _operation("initiative_closed"),
        }
        self._require(
            control=_control(None),
            records=closed_records,
            lifecycle=lifecycle,
        )
        self._require(
            control=_control("INI-SUCCESSOR"),
            records=closed_records,
            lifecycle=lifecycle,
        )

        reactivated = _control(INITIATIVE_ID)
        with self.assertRaisesRegex(RuntimeError, "terminal binding drifted"):
            self._require(
                control=reactivated,
                records=closed_records,
                lifecycle=lifecycle,
            )
        with self.assertRaisesRegex(RuntimeError, "close lacks its open"):
            self._require(
                control=_control(None),
                records={
                    (
                        "operation",
                        PREFIX + "close-initiative",
                    ): _operation("initiative_closed")
                },
                lifecycle=lifecycle,
            )

    def test_terminal_borrow_accepts_only_a_later_owner_close(self) -> None:
        resolution = _operation(
            "historical_replay_obligations_resolved",
            sequence=10,
        )
        initiative = SimpleNamespace(
            status="open",
            subject=f"Initiative:{INITIATIVE_ID}",
        )
        records = {
            ("initiative-open", INITIATIVE_ID): initiative,
            ("operation", PREFIX + "resolve-replay"): resolution,
        }
        owner_close = _owner_close(11)
        require_replay_initiative_binding(
            control=_control(None, sequence=11),
            index=_index(records, subject_status_records=(owner_close,)),
            lifecycle=ReplayInitiativeLifecycle.BORROW_ACTIVE_INITIATIVE,
            mission_id=MISSION_ID,
            initiative_id=INITIATIVE_ID,
            operation_prefix=PREFIX,
            phase=ReplayInitiativeBindingPhase.TERMINAL_HANDOFF,
        )

        attacks = (
            (_control(None, sequence=10), (owner_close,)),
            (
                _control(None, sequence=11),
                (
                    _owner_close(9),
                ),
            ),
            (_control(None, sequence=11), ()),
        )
        for control, closes in attacks:
            with self.subTest(control=control, closes=closes):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "exact active Initiative",
                ):
                    require_replay_initiative_binding(
                        control=control,
                        index=_index(records, subject_status_records=closes),
                        lifecycle=(
                            ReplayInitiativeLifecycle.BORROW_ACTIVE_INITIATIVE
                        ),
                        mission_id=MISSION_ID,
                        initiative_id=INITIATIVE_ID,
                        operation_prefix=PREFIX,
                        phase=ReplayInitiativeBindingPhase.TERMINAL_HANDOFF,
                    )

    def test_terminal_owned_architecture_handoff_accepts_owner_close_and_successor(
        self,
    ) -> None:
        successor_id = "INI-SUCCESSOR"
        records = {
            (
                "operation",
                PREFIX + "open-initiative",
            ): _operation("initiative_opened"),
            (
                "operation",
                PREFIX + "resolve-replay",
            ): _operation(
                "historical_replay_obligations_deferred",
                sequence=10,
            ),
            ("initiative-open", successor_id): SimpleNamespace(
                status="open",
                subject=f"Initiative:{successor_id}",
            ),
        }
        owner_close = _owner_close(11)
        control = _control(successor_id, sequence=12)
        require_replay_initiative_binding(
            control=control,
            index=_index(records, subject_status_records=(owner_close,)),
            lifecycle=ReplayInitiativeLifecycle.OWN_BOUNDED_INITIATIVE,
            mission_id=MISSION_ID,
            initiative_id=INITIATIVE_ID,
            operation_prefix=PREFIX,
            phase=ReplayInitiativeBindingPhase.TERMINAL_HANDOFF,
        )

    def test_consumed_resolution_prefix_cannot_reopen_nonterminal_obligation(
        self,
    ) -> None:
        spec = SimpleNamespace(
            initiative_id=INITIATIVE_ID,
            initiative_lifecycle=(
                ReplayInitiativeLifecycle.BORROW_ACTIVE_INITIATIVE
            ),
            mission_id=MISSION_ID,
            operation_prefix=PREFIX,
            study_id="STU-FIXTURE",
            target_obligation_id=(
                "historical-replay-obligation:" + "a" * 64
            ),
        )
        records = {
            (
                "operation",
                PREFIX + "resolve-replay",
            ): _operation("historical_replay_obligations_resolved"),
        }
        with self.assertRaisesRegex(RuntimeError, "fresh workflow identities"):
            replay_initiative_binding_phase(
                control=_control(INITIATIVE_ID),
                index=_index(records),
                spec=spec,
                target_head=SimpleNamespace(status="pending"),
            )

if __name__ == "__main__":
    unittest.main()
