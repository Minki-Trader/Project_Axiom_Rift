from __future__ import annotations

import unittest

from axiom_rift.operations.external_dependency import (
    ExternalDependencyContractError,
    ExternalRecoveryPath,
    ExternalRecoveryPlan,
    ExternalResumeAction,
    ExternalResumeCondition,
)


class ExternalResumeActionTests(unittest.TestCase):
    def test_v2_replay_scheduler_action_round_trips_and_freezes_nested_values(
        self,
    ) -> None:
        obligation_ids = [
            "historical-replay-obligation:" + "1" * 64,
            "historical-replay-obligation:" + "2" * 64,
        ]
        next_action = {
            "kind": "choose_next_initiative_or_terminal",
            "mission_id": "MIS-REPLAY-WAIT",
            "pending_replay_obligation_ids": obligation_ids,
            "required_replay_priority": "p1",
        }
        action = ExternalResumeAction.from_next_action(next_action)
        identity = action.identity
        obligation_ids.append(
            "historical-replay-obligation:" + "3" * 64
        )

        self.assertEqual(
            action.to_next_action()["pending_replay_obligation_ids"],
            [
                "historical-replay-obligation:" + "1" * 64,
                "historical-replay-obligation:" + "2" * 64,
            ],
        )
        self.assertEqual(action.identity, identity)
        rebuilt = ExternalResumeAction.from_identity_payload(
            action.to_identity_payload()
        )
        self.assertEqual(rebuilt, action)
        plan = ExternalRecoveryPlan(
            boundary_event_id="4" * 64,
            condition=ExternalResumeCondition(
                dependency_id="required-history-service",
                dependency_kind="market_data_service",
                blocked_mission_capability="source replacement capability",
                required_external_change="history service becomes available",
                validator_id="validator:" + "5" * 64,
                validation_plan_hash="6" * 64,
                resume_action=action,
            ),
            paths=(
                ExternalRecoveryPath(
                    recovery_kind="external_probe",
                    recovery_path_id="probe",
                ),
                ExternalRecoveryPath(
                    recovery_kind="local_recovery",
                    recovery_path_id="local-recovery",
                ),
                ExternalRecoveryPath(
                    recovery_kind="safe_substitute_search",
                    recovery_path_id="substitute-search",
                ),
            ),
        )
        self.assertEqual(
            ExternalRecoveryPlan.from_identity_payload(
                plan.to_identity_payload()
            ),
            plan,
        )

    def test_replay_scheduler_action_rejects_partial_or_noncanonical_bindings(
        self,
    ) -> None:
        obligation_a = "historical-replay-obligation:" + "a" * 64
        obligation_b = "historical-replay-obligation:" + "b" * 64
        invalid_actions = (
            {
                "kind": "choose_next_initiative_or_terminal",
                "mission_id": "MIS-REPLAY-WAIT",
                "pending_replay_obligation_ids": [obligation_a],
            },
            {
                "kind": "choose_next_initiative_or_terminal",
                "mission_id": "MIS-REPLAY-WAIT",
                "pending_replay_obligation_ids": [obligation_b, obligation_a],
                "required_replay_priority": "p1",
            },
            {
                "kind": "choose_next_initiative_or_terminal",
                "mission_id": "MIS-REPLAY-WAIT",
                "pending_replay_obligation_ids": [obligation_a, obligation_a],
                "required_replay_priority": "p1",
            },
            {
                "kind": "choose_next_initiative_or_terminal",
                "mission_id": "MIS-REPLAY-WAIT",
                "pending_replay_obligation_ids": ["not-an-obligation"],
                "required_replay_priority": "p1",
            },
            {
                "kind": "choose_next_initiative_or_terminal",
                "mission_id": "MIS-REPLAY-WAIT",
                "pending_replay_obligation_ids": [obligation_a],
                "required_replay_priority": "high",
            },
            {
                "kind": "choose_next_initiative_or_terminal",
                "mission_id": "MIS-REPLAY-WAIT",
                "pending_replay_obligation_ids": [obligation_a],
                "required_replay_priority": "p1",
                "caller_note": {"unsafe": "extra authority"},
            },
        )
        for action in invalid_actions:
            with self.subTest(action=action), self.assertRaises(
                ExternalDependencyContractError
            ):
                ExternalResumeAction.from_next_action(action)

        canonical = ExternalResumeAction.from_next_action(
            {
                "kind": "choose_next_initiative_or_terminal",
                "mission_id": "MIS-REPLAY-WAIT",
                "pending_replay_obligation_ids": [obligation_a],
                "required_replay_priority": "p1",
            }
        ).to_identity_payload()
        canonical["bindings"] = list(reversed(canonical["bindings"]))
        with self.assertRaisesRegex(
            ExternalDependencyContractError,
            "not canonical",
        ):
            ExternalResumeAction.from_identity_payload(canonical)

    def test_open_initiative_keeps_its_exact_scalar_binding(self) -> None:
        action = ExternalResumeAction.from_next_action(
            {
                "kind": "open_initiative",
                "mission_id": "MIS-INTAKE-WAIT",
                "research_intake_id": "research-intake:" + "7" * 64,
            }
        )
        self.assertEqual(
            action.to_next_action(),
            {
                "kind": "open_initiative",
                "mission_id": "MIS-INTAKE-WAIT",
                "research_intake_id": "research-intake:" + "7" * 64,
            },
        )


if __name__ == "__main__":
    unittest.main()
