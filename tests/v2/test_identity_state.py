from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from axiom_rift.v2.identity import IdentityError, ObjectStore
from axiom_rift.v2.state.store import ControlStateError, ControlStore
from axiom_rift.v2.state.transitions import (
    TransitionError,
    make_next_action,
    promote_claim,
    transition_stage,
    validate_next_action,
)


def bootstrap_state() -> dict:
    return {
        "schema": "axiom_rift_v2_control_state_v1",
        "revision": 1,
        "status": "bootstrap",
        "active_truth": "v1_until_v2_activation",
        "goal_id": "V2G0001",
        "namespace": {},
        "cursor": {
            "stage": "bootstrap",
            "stage_id": "V2B0001",
            "stage_status": "in_progress",
            "terminal_outcome": None,
            "exact_next_action": "build",
        },
        "reentry": {},
        "claim": {
            "current_level": "none",
            "claim_ceiling": "none",
            "basis_receipt_ids": [],
        },
        "ledger_heads": {},
        "applied_idempotency_keys": [],
    }


class ObjectStoreTests(unittest.TestCase):
    def test_put_is_idempotent_and_tamper_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ObjectStore(Path(temp_dir) / "objects")
            object_id = store.put("test", {"value": 1})
            self.assertEqual(object_id, store.put("test", {"value": 1}))
            path = store.path_for(object_id)
            path.write_text('{"object_id":"' + object_id + '","kind":"test","payload":{"value":2},"schema":"axiom_rift_v2_object_v1"}\n', encoding="ascii")
            with self.assertRaises(IdentityError):
                store.get(object_id)


class ControlStoreTests(unittest.TestCase):
    def test_cas_commit_and_idempotency(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.yaml"
            path.write_text(yaml.safe_dump(bootstrap_state(), sort_keys=False), encoding="ascii")
            store = ControlStore(path)
            updated = store.commit(1, "k1", lambda state: state)
            self.assertEqual(2, updated["revision"])
            repeated = store.commit(2, "k1", lambda state: (_ for _ in ()).throw(AssertionError()))
            self.assertEqual(2, repeated["revision"])
            with self.assertRaises(ControlStateError):
                store.commit(1, "k2", lambda state: state)

    def test_replace_failure_keeps_previous_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.yaml"
            original = yaml.safe_dump(bootstrap_state(), sort_keys=False)
            path.write_text(original, encoding="ascii")
            store = ControlStore(path, replace_func=lambda _source, _target: (_ for _ in ()).throw(OSError("boom")))
            with self.assertRaises(ControlStateError):
                store.commit(1, "k1", lambda state: state)
            self.assertEqual(original, path.read_text(encoding="ascii"))

    def test_stage_and_claim_skip_are_rejected(self) -> None:
        cursor = bootstrap_state()["cursor"]
        with self.assertRaises(TransitionError):
            transition_stage(cursor, "R", "V2R0001")
        with self.assertRaises(TransitionError):
            promote_claim({"current_level": "none"}, "research_candidate", ["V2E000001"])

    def test_root_close_action_requires_complete_exact_arguments(self) -> None:
        action = make_next_action(
            "close_root_mission",
            mission_id="AXIOM_ROOT_0001",
            terminal_outcome="closed_no_candidate",
            basis_evidence_id="V2E000100",
            prerequisite_receipt_ids=["V2E000100"],
        )
        validate_next_action(action)
        self.assertEqual("AXIOM_ROOT_0001", action["mission_id"])
        with self.assertRaises(TransitionError):
            make_next_action("close_root_mission")
        with self.assertRaises(TransitionError):
            make_next_action(
                "open_goal",
                goal_id="V2G0001",
                mission_id="AXIOM_ROOT_0001",
            )


if __name__ == "__main__":
    unittest.main()
