from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from axiom_rift.operations.replay_projection import (
    ReplayTransitionError,
    constraints_for_pending,
    initial_obligation_record,
    prepare_execution_progress,
    require_study_execution_complete,
    validate_decision_selection,
    validate_snapshot_scheduler_projection,
    with_scheduler_constraints,
)
from axiom_rift.research.historical_adjudication import ReplayPriority
from axiom_rift.research.replay_obligation import (
    derive_historical_replay_obligation,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex


MISSION_ID = "MIS-MULTI-REPLAY"
DECISION_ID = "decision:" + "d" * 64


def _adjudication_payload(
    token: int,
    priority: ReplayPriority = ReplayPriority.P1,
) -> dict[str, object]:
    return {
        "adjudication": {
            "candidate_eligible": False,
            "claims": [{"claim_id": f"claim-{token}"}],
            "criteria": [{"criterion_id": f"criterion-{token}"}],
        },
        "audit_artifact_hash": f"{token + 10:064x}",
        "completion_record_id": f"{token + 20:064x}",
        "disposition": "replay_required",
        "executable_id": f"executable:{token + 30:064x}",
        "measurement_artifact_hash": f"{token + 40:064x}",
        "reason_codes": ["missing_exact_uncertainty"],
        "replay_priority": priority.value,
        "schema": "historical_scientific_adjudication.v2",
        "study_close_record_id": f"{token + 50:064x}",
        "study_id": f"STU-{token:04d}",
        "validation_plan_hash": f"{token + 60:064x}",
    }


class MultiExecutableReplayProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.index = LocalIndex(Path(self.temporary.name) / "index.sqlite3")
        self.addCleanup(self.index.close)
        self.obligations = tuple(
            derive_historical_replay_obligation(
                governing_mission_id=MISSION_ID,
                historical_adjudication_id=(
                    f"historical-adjudication:{token:064x}"
                ),
                adjudication_payload=_adjudication_payload(token),
            )
            for token in range(1, 5)
        )
        records: list[IndexRecord] = []
        for token, obligation in enumerate(self.obligations, start=1):
            records.extend(
                (
                    IndexRecord(
                        kind="historical-scientific-adjudication",
                        record_id=obligation.historical_adjudication_id,
                        subject=f"Study:{obligation.original_study_id}",
                        status="replay_required",
                        fingerprint=f"{token:064x}",
                        payload=_adjudication_payload(token),
                    ),
                    initial_obligation_record(obligation),
                )
            )
        self.index.put_many(records)
        self.study = IndexRecord(
            kind="study-open",
            record_id="STU-MULTI-REPLAY",
            subject=f"Mission:{MISSION_ID}",
            status="open",
            fingerprint="a" * 64,
            payload={
                "mission_id": MISSION_ID,
                "portfolio_decision_id": DECISION_ID,
                "replay_obligation_ids": sorted(
                    item.identity for item in self.obligations
                ),
            },
        )
        self.index.put(self.study)

    @staticmethod
    def _executable_payload(
        reference: str | None = None,
        *,
        duplicate_declaration: bool = False,
    ) -> dict[str, object]:
        if reference is None:
            return {"schema": "ordinary_control_trial.v1"}
        declaration = {
            "spec": {
                "parameter_fields": ["historical_reference_executable_id"]
            }
        }
        manifests = [declaration]
        if duplicate_declaration:
            manifests.append(declaration)
        return {
            "component_manifests": manifests,
            "parameters": {"historical_reference_executable_id": reference},
            "schema": "multi_replay_trial_fixture.v1",
        }

    @staticmethod
    def _trial_record(
        *,
        study_id: str,
        executable_id: str,
        executable_payload: dict[str, object],
        obligation_ids: tuple[str, ...],
    ) -> IndexRecord:
        return IndexRecord(
            kind="trial",
            record_id=executable_id,
            subject="Batch:BAT-MULTI-REPLAY",
            status="evaluated",
            fingerprint=executable_id.removeprefix("executable:"),
            payload={
                "executable": executable_payload,
                "replay_obligation_ids": list(obligation_ids),
                "study_id": study_id,
            },
        )

    def _register_matching_trial(self, ordinal: int) -> str:
        obligation = self.obligations[ordinal - 1]
        executable_id = f"executable:{ordinal + 100:064x}"
        executable_payload = self._executable_payload(
            obligation.original_executable_id
        )
        matched, progress = prepare_execution_progress(
            self.index,
            study_record=self.study,
            executable_id=executable_id,
            executable_payload=executable_payload,
        )
        self.assertEqual(matched, (obligation.identity,))
        self.index.put_many(
            (
                *progress,
                self._trial_record(
                    study_id=self.study.record_id,
                    executable_id=executable_id,
                    executable_payload=executable_payload,
                    obligation_ids=matched,
                ),
            )
        )
        return executable_id

    def test_four_trial_family_advances_one_obligation_per_exact_manifest(self) -> None:
        unmatched, records = prepare_execution_progress(
            self.index,
            study_record=self.study,
            executable_id="executable:" + "9" * 64,
            executable_payload=self._executable_payload(),
        )
        self.assertEqual(unmatched, ())
        self.assertEqual(records, [])

        with self.assertRaisesRegex(
            ReplayTransitionError, "not one typed component field"
        ):
            prepare_execution_progress(
                self.index,
                study_record=self.study,
                executable_id="executable:" + "8" * 64,
                executable_payload=self._executable_payload(
                    self.obligations[0].original_executable_id,
                    duplicate_declaration=True,
                ),
            )

        first_executable_id = self._register_matching_trial(1)
        duplicate, duplicate_records = prepare_execution_progress(
            self.index,
            study_record=self.study,
            executable_id=first_executable_id,
            executable_payload=self._executable_payload(
                self.obligations[0].original_executable_id
            ),
        )
        self.assertEqual(duplicate, ())
        self.assertEqual(duplicate_records, [])

        for ordinal in (2, 3):
            self._register_matching_trial(ordinal)
        with self.assertRaisesRegex(
            ReplayTransitionError, "one exact trial per obligation"
        ):
            require_study_execution_complete(
                self.index,
                mission_id=MISSION_ID,
                study=self.study,
            )

        self._register_matching_trial(4)
        self.assertEqual(
            require_study_execution_complete(
                self.index,
                mission_id=MISSION_ID,
                study=self.study,
            ),
            tuple(self.study.payload["replay_obligation_ids"]),
        )
        post_family, post_family_records = prepare_execution_progress(
            self.index,
            study_record=self.study,
            executable_id="executable:" + "7" * 64,
            executable_payload={"schema": "post_family_control_trial.v1"},
        )
        self.assertEqual(post_family, ())
        self.assertEqual(post_family_records, [])

    def test_matching_obligation_cannot_move_to_another_study(self) -> None:
        self._register_matching_trial(1)
        other_study = IndexRecord(
            kind="study-open",
            record_id="STU-OTHER-REPLAY",
            subject=f"Mission:{MISSION_ID}",
            status="open",
            fingerprint="b" * 64,
            payload={
                "mission_id": MISSION_ID,
                "portfolio_decision_id": DECISION_ID,
                "replay_obligation_ids": [self.obligations[0].identity],
            },
        )
        with self.assertRaisesRegex(
            ReplayTransitionError, "already bound to another trial or Study"
        ):
            prepare_execution_progress(
                self.index,
                study_record=other_study,
                executable_id="executable:" + "6" * 64,
                executable_payload=self._executable_payload(
                    self.obligations[0].original_executable_id
                ),
            )

    def test_scheduler_exposes_only_p0_while_any_p0_is_pending(self) -> None:
        p1 = self.obligations[0]
        p0 = derive_historical_replay_obligation(
            governing_mission_id=MISSION_ID,
            historical_adjudication_id=(
                "historical-adjudication:" + "f" * 64
            ),
            adjudication_payload=_adjudication_payload(
                99,
                ReplayPriority.P0,
            ),
        )
        constraints = constraints_for_pending((p1, p0))
        assert constraints is not None
        self.assertEqual(constraints["required_replay_priority"], "p0")
        self.assertEqual(
            constraints["pending_replay_obligation_ids"],
            [p0.identity],
        )

    def test_diagnosis_cleanup_may_dispose_exact_axis_with_pending_replays(
        self,
    ) -> None:
        axis_id = "axis-completed-replay"
        snapshot_id = "portfolio:" + "7" * 64
        diagnosis_id = "diagnosis:" + "8" * 64
        self.index.put(
            IndexRecord(
                kind="study-diagnosis",
                record_id=diagnosis_id,
                subject="Study:STU-COMPLETED-REPLAY",
                status="supported_requires_confirmation",
                fingerprint="8" * 64,
                payload={
                    "mission_id": MISSION_ID,
                    "portfolio_axis_id": axis_id,
                    "portfolio_snapshot_id": snapshot_id,
                },
            )
        )
        constraints = constraints_for_pending(self.obligations)
        assert constraints is not None
        next_action = {
            "kind": "portfolio_decision",
            **constraints,
            "portfolio_snapshot_id": snapshot_id,
            "study_diagnosis_id": diagnosis_id,
        }
        work_actions = frozenset(
            {"contrast", "deepen", "recombine", "rotate", "synthesize"}
        )

        self.assertEqual(
            validate_decision_selection(
                self.index,
                mission_id=MISSION_ID,
                next_action=next_action,
                replay_obligation_ids=(),
                action="preserve",
                target_axis_id=axis_id,
                work_actions=work_actions,
            ),
            constraints,
        )
        snapshot_action = with_scheduler_constraints(
            {
                "action": "preserve",
                "decision_id": "decision:" + "9" * 64,
                "kind": "record_portfolio_snapshot",
            },
            constraints,
        )
        self.assertEqual(
            {
                name: snapshot_action[name]
                for name in (
                    "pending_replay_obligation_ids",
                    "required_replay_priority",
                )
            },
            constraints,
        )
        self.assertTrue(
            validate_snapshot_scheduler_projection(
                next_action={
                    "action": "preserve",
                    "decision_id": "decision:" + "9" * 64,
                    "kind": "record_portfolio_snapshot",
                },
                decision_payload={
                    "scheduler_constraints": constraints,
                    "study_diagnosis_id": diagnosis_id,
                },
                constraints=constraints,
            )
        )
        self.assertFalse(
            validate_snapshot_scheduler_projection(
                next_action=snapshot_action,
                decision_payload={
                    "scheduler_constraints": constraints,
                    "study_diagnosis_id": diagnosis_id,
                },
                constraints=constraints,
            )
        )
        with self.assertRaisesRegex(
            ReplayTransitionError,
            "Portfolio mutation replay scheduler authority is stale",
        ):
            validate_snapshot_scheduler_projection(
                next_action={
                    "action": "new_mechanism",
                    "decision_id": "decision:" + "9" * 64,
                    "kind": "record_portfolio_snapshot",
                },
                decision_payload={
                    "scheduler_constraints": constraints,
                    "study_diagnosis_id": diagnosis_id,
                },
                constraints=constraints,
            )
        with self.assertRaisesRegex(
            ReplayTransitionError,
            "pending replay permits only bound work or a new-mechanism bridge",
        ):
            validate_decision_selection(
                self.index,
                mission_id=MISSION_ID,
                next_action=next_action,
                replay_obligation_ids=(),
                action="prune",
                target_axis_id="axis-unrelated",
                work_actions=work_actions,
            )


if __name__ == "__main__":
    unittest.main()
