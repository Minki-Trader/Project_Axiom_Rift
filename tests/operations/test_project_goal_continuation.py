from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.permits import SubjectKind
from axiom_rift.operations.writer import StateWriter, TransitionError, _record


REPO_ROOT = Path(__file__).resolve().parents[2]


def mission_goal(tag: str) -> dict[str, object]:
    return {
        "objective": f"Continue the persistent Project Goal through {tag}",
        "scope": [
            "this_repository",
            "this_pc",
            "current_python_environment",
            "current_fpmarkets_mt5_environment",
            "pre_live_only",
        ],
        "terminal_contract": (
            "completed_pre_live_handoff_or_closed_no_candidate_or_blocked_external"
        ),
    }


def successor_basis(
    close_record_id: str,
    *,
    reason: str = "Continue with a distinct bounded Mission under the same Project Goal",
) -> dict[str, str]:
    return {
        "continuation_reason": reason,
        "predecessor_mission_close_record_id": close_record_id,
    }


class ProjectGoalContinuationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.writer = StateWriter(self.root, foundation_root=REPO_ROOT)
        self.writer.initialize_ready()

    def _open_fresh(self, mission_id: str = "MIS-0001") -> None:
        self.writer.open_mission(
            mission_id=mission_id,
            goal=mission_goal(mission_id),
            operation_id=f"open-{mission_id.lower()}",
        )

    def _seed_negative_terminal(self, mission_id: str, tag: str) -> str:
        basis_id = canonical_digest(
            domain="project-goal-negative-terminal-fixture",
            payload={"mission_id": mission_id, "tag": tag},
        )

        def prepare(current, _index):
            if current is None:
                raise AssertionError("fixture requires initialized control")
            body = self.writer._body(current)
            science = body["scientific"]
            if science["active_mission"] != mission_id:
                raise AssertionError("fixture Mission differs")
            body["next_action"] = {
                "basis_record_id": basis_id,
                "kind": "close_mission",
                "outcome": "closed_no_candidate",
            }
            record = _record(
                kind="exhaustion-audit",
                record_id=basis_id,
                subject=f"Mission:{mission_id}",
                status="accepted",
                fingerprint=basis_id,
                payload={"fixture": tag},
            )
            return body, [record], {"basis_record_id": basis_id}

        self.writer._commit(
            event_kind="negative_terminal_fixture_seeded",
            operation_id=f"seed-negative-{tag}",
            subject=f"Mission:{mission_id}",
            payload={"basis_record_id": basis_id},
            prepare=prepare,
        )
        return basis_id

    def _seed_positive_terminal(self, mission_id: str, tag: str) -> str:
        executable_id = "executable:" + canonical_digest(
            domain="project-goal-positive-executable-fixture",
            payload={"mission_id": mission_id, "tag": tag},
        )
        candidate_id = "candidate:" + canonical_digest(
            domain="project-goal-positive-candidate-fixture",
            payload={"executable_id": executable_id},
        )
        release_id = "release:" + canonical_digest(
            domain="project-goal-positive-release-fixture",
            payload={"candidate_id": candidate_id},
        )

        def prepare(current, _index):
            if current is None:
                raise AssertionError("fixture requires initialized control")
            body = self.writer._body(current)
            science = body["scientific"]
            if science["active_mission"] != mission_id:
                raise AssertionError("fixture Mission differs")
            science["active_executable"] = executable_id
            science["active_release"] = {
                "candidate_id": candidate_id,
                "executable_id": executable_id,
                "id": release_id,
                "status": "frozen",
            }
            authorization = self.writer._authorization(
                kind=SubjectKind.EXECUTABLE,
                subject_id=executable_id,
                semantic_hash=executable_id.removeprefix("executable:"),
            )
            self.writer._bind_authorization(body, authorization)
            body["next_action"] = {
                "basis_record_id": release_id,
                "kind": "close_mission",
                "outcome": "completed_pre_live_handoff",
            }
            record = _record(
                kind="release",
                record_id=release_id,
                subject=f"Release:{release_id}",
                status="frozen",
                fingerprint=release_id.removeprefix("release:"),
                payload={
                    "candidate_id": candidate_id,
                    "completion_record_ids": [],
                    "executable_id": executable_id,
                    "mission_id": mission_id,
                },
            )
            return body, [record], {"release_id": release_id}

        self.writer._commit(
            event_kind="positive_terminal_fixture_seeded",
            operation_id=f"seed-positive-{tag}",
            subject=f"Mission:{mission_id}",
            payload={"release_id": release_id},
            prepare=prepare,
        )
        return release_id

    def _seed_project_holdout_state(
        self,
        mission_id: str,
        *,
        reveal_count: int,
        required_holdout_id: str,
    ) -> None:
        record_id = canonical_digest(
            domain="project-goal-holdout-state-fixture",
            payload={
                "mission_id": mission_id,
                "required_holdout_id": required_holdout_id,
                "reveal_count": reveal_count,
            },
        )

        def prepare(current, _index):
            if current is None:
                raise AssertionError("fixture requires initialized control")
            body = self.writer._body(current)
            science = body["scientific"]
            if science["active_mission"] != mission_id:
                raise AssertionError("fixture Mission differs")
            science["holdout_reveals"] = reveal_count
            science["required_future_holdout_id"] = required_holdout_id
            record = _record(
                kind="project-holdout-state-fixture",
                record_id=record_id,
                subject="ProjectGoal:OPERATING_DIRECTION.md",
                status="observed",
                fingerprint=record_id,
                payload={
                    "mission_id": mission_id,
                    "required_holdout_id": required_holdout_id,
                    "reveal_count": reveal_count,
                },
            )
            return body, [record], {"record_id": record_id}

        self.writer._commit(
            event_kind="project_holdout_state_fixture_seeded",
            operation_id=f"seed-holdout-{mission_id.lower()}",
            subject="ProjectGoal:OPERATING_DIRECTION.md",
            payload={"record_id": record_id},
            prepare=prepare,
        )

    def _seed_legacy_negative_terminal(
        self,
        mission_id: str,
        tag: str,
        *,
        holdout_reveals: int = 0,
        required_future_holdout_id: str | None = None,
    ) -> tuple[str, str]:
        goal = mission_goal(f"legacy {mission_id}")
        goal_hash = canonical_digest(domain="mission-goal", payload=goal)
        basis_id = canonical_digest(
            domain="legacy-negative-terminal-basis-fixture",
            payload={"mission_id": mission_id, "tag": tag},
        )
        close_id = canonical_digest(
            domain="mission-close",
            payload={
                "basis": basis_id,
                "mission_id": mission_id,
                "outcome": "closed_no_candidate",
            },
        )

        def prepare(current, _index):
            if current is None:
                raise AssertionError("fixture requires initialized control")
            body = self.writer._body(current)
            science = body["scientific"]
            if body["next_action"] != {"kind": "await_root_goal"}:
                raise AssertionError("fixture requires the bare root boundary")
            if any(
                science.get(name) is not None
                for name in (
                    "active_mission",
                    "active_initiative",
                    "active_study",
                    "active_batch",
                    "active_job",
                    "active_repair",
                    "active_executable",
                    "active_lineage",
                    "active_release",
                    "active_holdout_evaluation",
                )
            ):
                raise AssertionError("fixture requires disposed scientific state")
            science["holdout_reveals"] = holdout_reveals
            science["required_future_holdout_id"] = required_future_holdout_id
            opened = _record(
                kind="mission-open",
                record_id=mission_id,
                subject=f"Mission:{mission_id}",
                status="open",
                fingerprint=goal_hash,
                payload={"goal": goal, "goal_hash": goal_hash},
            )
            basis = _record(
                kind="exhaustion-audit",
                record_id=basis_id,
                subject=f"Mission:{mission_id}",
                status="accepted",
                fingerprint=basis_id,
                payload={"fixture": tag},
            )
            closed = _record(
                kind="mission-close",
                record_id=close_id,
                subject=f"Mission:{mission_id}",
                status="closed_no_candidate",
                fingerprint=close_id,
                payload={"basis_record_id": basis_id},
            )
            return body, [opened, basis, closed], {
                "basis_record_id": basis_id,
                "mission_close_record_id": close_id,
            }

        self.writer._commit(
            event_kind="legacy_negative_terminal_fixture_seeded",
            operation_id=f"seed-legacy-negative-{tag}",
            subject=f"Mission:{mission_id}",
            payload={
                "basis_record_id": basis_id,
                "mission_close_record_id": close_id,
            },
            prepare=prepare,
        )
        return close_id, basis_id

    def _project_goal_adoption(self):
        with self.writer._open_authoritative_index() as index:
            record = index.event_record("project-goal:OPERATING_DIRECTION.md", 1)
        self.assertIsNotNone(record)
        return record

    def _close_negative(self, mission_id: str, tag: str):
        basis_id = self._seed_negative_terminal(mission_id, tag)
        result = self.writer.close_mission(
            outcome="closed_no_candidate",
            basis_record_id=basis_id,
            operation_id=f"close-negative-{tag}",
        )
        record = self._mission_close(mission_id, "closed_no_candidate")
        return result, record, basis_id

    def _mission_close(self, mission_id: str, outcome: str):
        with self.writer._open_authoritative_index() as index:
            matches = [
                record
                for record in index.records_by_subject_status(
                    subject=f"Mission:{mission_id}", status=outcome
                )
                if record.kind == "mission-close"
            ]
        self.assertEqual(len(matches), 1)
        return matches[0]

    def _mission_open(self, mission_id: str):
        with self.writer._open_authoritative_index() as index:
            record = index.get("mission-open", mission_id)
        self.assertIsNotNone(record)
        return record

    def test_fresh_ready_boundary_is_bare_and_initial_mission_has_no_successor_basis(
        self,
    ) -> None:
        self.assertEqual(
            self.writer.read_control()["next_action"],  # type: ignore[index]
            {"kind": "await_root_goal"},
        )

        self._open_fresh()

        opened = self._mission_open("MIS-0001")
        self.assertIsNone(opened.payload.get("successor_basis"))

    def test_negative_close_is_predecessor_bound_and_does_not_complete_project_goal(
        self,
    ) -> None:
        self._open_fresh()

        result, close, basis_id = self._close_negative("MIS-0001", "first")

        self.assertFalse(result.result["project_goal_complete"])
        self.assertFalse(close.payload["project_goal_complete"])
        self.assertEqual(
            self.writer.read_control()["next_action"],  # type: ignore[index]
            {
                "kind": "await_root_goal",
                "predecessor_basis_record_id": basis_id,
                "predecessor_mission_close_record_id": close.record_id,
                "predecessor_mission_id": "MIS-0001",
                "predecessor_outcome": "closed_no_candidate",
            },
        )

    def test_successor_requires_basis_and_derives_exact_predecessor(self) -> None:
        self._open_fresh()
        _, close, basis_id = self._close_negative("MIS-0001", "successor")

        with self.assertRaises(TransitionError):
            self.writer.open_mission(
                mission_id="MIS-0002",
                goal=mission_goal("MIS-0002"),
                operation_id="reject-successor-without-basis",
            )
        with self.assertRaises(TransitionError):
            self.writer.open_mission(
                mission_id="MIS-0002",
                goal=mission_goal("MIS-0002"),
                successor_basis=successor_basis("0" * 64),
                operation_id="reject-successor-with-wrong-predecessor",
            )

        supplied = successor_basis(close.record_id)
        self.writer.open_mission(
            mission_id="MIS-0002",
            goal=mission_goal("MIS-0002"),
            successor_basis=supplied,
            operation_id="open-successor-with-basis",
        )

        opened = self._mission_open("MIS-0002")
        self.assertEqual(
            opened.payload["successor_basis"],
            {
                "continuation_reason": supplied["continuation_reason"],
                "predecessor_basis_record_id": basis_id,
                "predecessor_mission_close_record_id": close.record_id,
                "predecessor_mission_id": "MIS-0001",
                "predecessor_outcome": "closed_no_candidate",
            },
        )

    def test_successor_chain_rejects_duplicate_identity_and_stale_history(self) -> None:
        self._open_fresh()
        _, first_close, _ = self._close_negative("MIS-0001", "chain-first")
        first_basis = successor_basis(first_close.record_id)

        with self.assertRaises(TransitionError):
            self.writer.open_mission(
                mission_id="MIS-0001",
                goal=mission_goal("duplicate MIS-0001"),
                successor_basis=first_basis,
                operation_id="reject-duplicate-mission-id",
            )
        self.writer.open_mission(
            mission_id="MIS-0002",
            goal=mission_goal("MIS-0002"),
            successor_basis=first_basis,
            operation_id="open-chain-second",
        )
        _, second_close, _ = self._close_negative("MIS-0002", "chain-second")

        with self.assertRaises(TransitionError):
            self.writer.open_mission(
                mission_id="MIS-0003",
                goal=mission_goal("stale predecessor"),
                successor_basis=first_basis,
                operation_id="reject-stale-predecessor-history",
            )
        self.writer.open_mission(
            mission_id="MIS-0003",
            goal=mission_goal("MIS-0003"),
            successor_basis=successor_basis(second_close.record_id),
            operation_id="open-chain-third",
        )
        self.assertEqual(
            self._mission_open("MIS-0003").payload["successor_basis"][
                "predecessor_mission_id"
            ],
            "MIS-0002",
        )

    def test_project_holdout_accounting_persists_across_successor_mission(self) -> None:
        self._open_fresh()
        required_holdout_id = "holdout:" + "a" * 64
        self._seed_project_holdout_state(
            "MIS-0001",
            reveal_count=1,
            required_holdout_id=required_holdout_id,
        )

        _, close, _ = self._close_negative("MIS-0001", "holdout")
        after_close = self.writer.read_control()
        self.assertEqual(after_close["scientific"]["holdout_reveals"], 1)  # type: ignore[index]
        self.assertEqual(
            after_close["scientific"]["required_future_holdout_id"],  # type: ignore[index]
            required_holdout_id,
        )

        self.writer.open_mission(
            mission_id="MIS-0002",
            goal=mission_goal("MIS-0002 holdout continuation"),
            successor_basis=successor_basis(close.record_id),
            operation_id="open-holdout-successor",
        )
        successor = self.writer.read_control()
        self.assertEqual(successor["scientific"]["holdout_reveals"], 1)  # type: ignore[index]
        self.assertEqual(
            successor["scientific"]["required_future_holdout_id"],  # type: ignore[index]
            required_holdout_id,
        )

    def test_positive_terminal_is_the_only_project_goal_completion(self) -> None:
        self._open_fresh()
        release_id = self._seed_positive_terminal("MIS-0001", "positive")

        with patch.object(
            self.writer,
            "_derive_release_basis_locked",
            return_value={},
        ):
            result = self.writer.close_mission(
                outcome="completed_pre_live_handoff",
                basis_record_id=release_id,
                operation_id="close-positive-project-goal",
            )

        close = self._mission_close("MIS-0001", "completed_pre_live_handoff")
        self.assertTrue(result.result["project_goal_complete"])
        self.assertTrue(close.payload["project_goal_complete"])
        self.assertEqual(
            self.writer.read_control()["next_action"],  # type: ignore[index]
            {
                "kind": "project_goal_complete",
                "mission_close_record_id": close.record_id,
                "outcome": "completed_pre_live_handoff",
            },
        )
        with self.assertRaises(TransitionError):
            self.writer.open_mission(
                mission_id="MIS-0002",
                goal=mission_goal("must not reopen after completion"),
                operation_id="reject-reopen-after-project-goal-completion",
            )

    def test_legacy_negative_terminal_requires_adoption_before_successor_open(
        self,
    ) -> None:
        close_id, _ = self._seed_legacy_negative_terminal(
            "MIS-0001", "admission-gate"
        )
        before = self.writer.read_control()
        self.assertEqual(before["next_action"], {"kind": "await_root_goal"})

        with self.assertRaises(TransitionError):
            self.writer.open_mission(
                mission_id="MIS-0002",
                goal=mission_goal("must activate legacy continuation first"),
                operation_id="reject-unadopted-legacy-successor",
            )

        self.assertEqual(self.writer.read_control(), before)
        with self.writer._open_authoritative_index() as index:
            self.assertIsNone(index.get("mission-open", "MIS-0002"))

        self.writer.activate_project_goal_continuation(
            predecessor_mission_id="MIS-0001",
            predecessor_mission_close_record_id=close_id,
            operation_id="activate-legacy-admission-gate",
        )
        self.writer.open_mission(
            mission_id="MIS-0002",
            goal=mission_goal("adopted legacy successor"),
            successor_basis=successor_basis(close_id),
            operation_id="open-adopted-legacy-successor",
        )
        self.assertEqual(
            self.writer.read_control()["scientific"]["active_mission"],  # type: ignore[index]
            "MIS-0002",
        )

    def test_legacy_negative_terminal_adoption_links_exact_boundary_without_delta(
        self,
    ) -> None:
        close_id, basis_id = self._seed_legacy_negative_terminal(
            "MIS-0001",
            "adopt",
            holdout_reveals=2,
        )
        before = self.writer.read_control()
        with self.writer._open_authoritative_index() as index:
            terminal_before = index.get("mission-close", close_id)

        result = self.writer.activate_project_goal_continuation(
            predecessor_mission_id="MIS-0001",
            predecessor_mission_close_record_id=close_id,
            operation_id="activate-legacy-project-goal",
        )

        after = self.writer.read_control()
        adoption = self._project_goal_adoption()
        with self.writer._open_authoritative_index() as index:
            terminal_after = index.get("mission-close", close_id)
        self.assertFalse(result.reused)
        self.assertEqual(
            result.result,
            {"adoption_id": adoption.record_id, "next_mission_ordinal": 2},
        )
        self.assertEqual(after["scientific"], before["scientific"])
        self.assertEqual(after["authorizations"], before["authorizations"])
        self.assertEqual(terminal_after, terminal_before)
        self.assertEqual(
            after["next_action"],
            {
                "kind": "await_root_goal",
                "predecessor_basis_record_id": basis_id,
                "predecessor_mission_close_record_id": close_id,
                "predecessor_mission_id": "MIS-0001",
                "predecessor_outcome": "closed_no_candidate",
            },
        )
        self.assertEqual(adoption.kind, "project-goal-adoption")
        self.assertEqual(adoption.subject, "ProjectGoal:OPERATING_DIRECTION.md")
        self.assertEqual(adoption.status, "active")
        self.assertEqual(adoption.fingerprint, adoption.record_id)
        self.assertEqual(adoption.event_sequence, 1)
        self.assertEqual(
            adoption.payload,
            {
                "adopted_mission_close_record_id": close_id,
                "basis_record_id": basis_id,
                "mission_id": "MIS-0001",
                "no_retroactive_authorization": True,
                "project_goal_authority": "OPERATING_DIRECTION.md",
                "schema": "project_goal_continuation_adoption.v1",
            },
        )

    def test_legacy_negative_terminal_adoption_rejects_wrong_and_stale_basis(
        self,
    ) -> None:
        first_close_id, _ = self._seed_legacy_negative_terminal(
            "MIS-0001", "stale-first"
        )
        latest_close_id, _ = self._seed_legacy_negative_terminal(
            "MIS-0002", "stale-latest"
        )
        first_close = self._mission_close("MIS-0001", "closed_no_candidate")
        latest_close = self._mission_close("MIS-0002", "closed_no_candidate")
        self.assertIsInstance(first_close.authority_sequence, int)
        self.assertIsInstance(latest_close.authority_sequence, int)
        self.assertLess(first_close.authority_sequence, latest_close.authority_sequence)

        with self.assertRaises(TransitionError):
            self.writer.activate_project_goal_continuation(
                predecessor_mission_id="MIS-0001",
                predecessor_mission_close_record_id=latest_close_id,
                operation_id="reject-wrong-legacy-predecessor",
            )
        with self.assertRaises(TransitionError):
            self.writer.activate_project_goal_continuation(
                predecessor_mission_id="MIS-0001",
                predecessor_mission_close_record_id=first_close_id,
                operation_id="reject-stale-legacy-predecessor",
            )

        accepted = self.writer.activate_project_goal_continuation(
            predecessor_mission_id="MIS-0002",
            predecessor_mission_close_record_id=latest_close_id,
            operation_id="accept-latest-legacy-predecessor",
        )
        self.assertFalse(accepted.reused)

    def test_legacy_negative_terminal_adoption_retry_is_idempotent(self) -> None:
        close_id, _ = self._seed_legacy_negative_terminal(
            "MIS-0001", "idempotent"
        )
        arguments = {
            "predecessor_mission_id": "MIS-0001",
            "predecessor_mission_close_record_id": close_id,
            "operation_id": "activate-legacy-idempotent",
        }

        first = self.writer.activate_project_goal_continuation(**arguments)
        control_after_first = self.writer.read_control()
        with self.writer._open_authoritative_index() as index:
            count_after_first = index.record_count()
        second = self.writer.activate_project_goal_continuation(**arguments)
        control_after_second = self.writer.read_control()
        with self.writer._open_authoritative_index() as index:
            count_after_second = index.record_count()
            project_head = index.event_head(
                "project-goal:OPERATING_DIRECTION.md"
            )

        self.assertFalse(first.reused)
        self.assertTrue(second.reused)
        self.assertEqual(second.result, first.result)
        self.assertEqual(second.event_id, first.event_id)
        self.assertEqual(second.revision, first.revision)
        self.assertEqual(control_after_second, control_after_first)
        self.assertEqual(count_after_second, count_after_first)
        self.assertIsNotNone(project_head)
        self.assertEqual(project_head.sequence, 1)

    def test_file_is_ascii(self) -> None:
        Path(__file__).read_text(encoding="ascii")


if __name__ == "__main__":
    unittest.main()
