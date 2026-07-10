#!/usr/bin/env python3
"""Apply the reviewed V2 P0 lifecycle and Git-freshness hardening.

This script is intentionally fail-closed. It verifies the exact source snippets
reviewed against main before writing any file. Run from the repository root,
inspect the resulting diff, then execute the focused tests listed at the end.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="ascii")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one reviewed snippet in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="ascii", newline="\n")


def main() -> None:
    transitions = ROOT / "src/axiom_rift/v2/state/transitions.py"
    store = ROOT / "src/axiom_rift/v2/state/store.py"
    operations = ROOT / "src/axiom_rift/v2/operations.py"
    state_machine = ROOT / "contracts/v2/state_machine.yaml"

    replace_once(
        transitions,
        '''TERMINAL_OUTCOMES = {\n    "completed_pre_live_handoff",\n    "closed_no_candidate",\n    "blocked_external",\n    "stopped_by_user",\n}\n\nINTERNAL_GOAL_TERMINAL_OUTCOMES = TERMINAL_OUTCOMES\nROOT_TERMINAL_OUTCOMES = TERMINAL_OUTCOMES\n''',
        '''ROOT_TERMINAL_OUTCOMES = {\n    "completed_pre_live_handoff",\n    "closed_no_candidate",\n    "blocked_external",\n    "stopped_by_user",\n}\nINTERNAL_GOAL_TERMINAL_OUTCOMES = {\n    "completed_internal_goal",\n    "closed_no_candidate",\n    "blocked_internal",\n    "stopped_internal",\n}\nTERMINAL_OUTCOMES = ROOT_TERMINAL_OUTCOMES\n''',
    )
    replace_once(
        transitions,
        '''    "record_evidence",\n    "close_goal",\n    "repair",\n''',
        '''    "record_evidence",\n    "close_goal",\n    "close_root_mission",\n    "repair",\n''',
    )

    replace_once(
        store,
        '''    IDENTITY_SPECS,\n    ROOT_TERMINAL_OUTCOMES,\n''',
        '''    IDENTITY_SPECS,\n    INTERNAL_GOAL_TERMINAL_OUTCOMES,\n    ROOT_TERMINAL_OUTCOMES,\n''',
    )
    replace_once(
        store,
        '''CLOSED_GOAL_HISTORY_OUTCOMES = TERMINAL_OUTCOMES | {"completed_v2_activation"}\n''',
        '''CLOSED_GOAL_HISTORY_OUTCOMES = INTERNAL_GOAL_TERMINAL_OUTCOMES | {"completed_v2_activation"}\n''',
    )
    replace_once(
        store,
        '''        mutation: Callable[[dict[str, Any]], dict[str, Any] | None],\n        referenced_object_ids: Iterable[str] = (),\n    ) -> dict[str, Any]:\n''',
        '''        mutation: Callable[[dict[str, Any]], dict[str, Any] | None],\n        referenced_object_ids: Iterable[str] = (),\n        *,\n        preserve_git_sync: bool = False,\n    ) -> dict[str, Any]:\n''',
    )
    replace_once(
        store,
        '''            if not isinstance(draft, dict):\n                raise ControlStateError("state mutation must produce a mapping")\n            draft["revision"] = expected_revision + 1\n''',
        '''            if not isinstance(draft, dict):\n                raise ControlStateError("state mutation must produce a mapping")\n            if draft.get("schema") == CONTROL_STATE_SCHEMA_V2 and not preserve_git_sync:\n                reentry = draft.setdefault("reentry", {})\n                prior = reentry.get("git_sync")\n                reentry["git_sync"] = {\n                    "status": "unsynced",\n                    "invalidated_by_operation": idempotency_key,\n                    "previous_validated_content_commit": (\n                        prior.get("validated_content_commit")\n                        if isinstance(prior, dict)\n                        else None\n                    ),\n                }\n            draft["revision"] = expected_revision + 1\n''',
    )

    replace_once(
        operations,
        '''        return self.control.commit(\n            state["revision"],\n            idempotency_key,\n            mutate,\n            referenced_object_ids=[receipt_object_id, object_id],\n        )\n\n    def issue_holdout_permit(\n''',
        '''        return self.control.commit(\n            state["revision"],\n            idempotency_key,\n            mutate,\n            referenced_object_ids=[receipt_object_id, object_id],\n            preserve_git_sync=True,\n        )\n\n    def issue_holdout_permit(\n''',
    )
    replace_once(
        operations,
        '''        if next_action is None:\n            if outcome == "completed_pre_live_handoff":\n                next_action = make_next_action("none", summary="root mission completed")\n            elif outcome in {"blocked_external", "stopped_by_user"}:\n                next_action = make_next_action("none", summary=f"internal goal ended: {outcome}")\n            else:\n                next_action = make_next_action(\n                    "open_goal",\n                    goal_id=format_identity("goal", state["namespace"]["next_goal"]),\n                    summary="open the next internal research goal",\n                )\n''',
        '''        if next_action is None:\n            if outcome == "completed_internal_goal":\n                next_action = make_next_action(\n                    "close_root_mission",\n                    summary="close the root mission from durable terminal evidence",\n                )\n            else:\n                next_action = make_next_action(\n                    "open_goal",\n                    goal_id=format_identity("goal", state["namespace"]["next_goal"]),\n                    summary="open the next internal research goal",\n                )\n''',
    )
    replace_once(
        operations,
        '''            self._set_next_action(draft, next_action)\n            draft["claim"] = {\n                "subject_kind": "none",\n                "subject_id": None,\n                "current_level": "none",\n                "claim_ceiling": "none",\n                "identity_bundle_object_id": None,\n                "basis_receipt_ids": [],\n                "blocked_by": [],\n            }\n''',
        '''            self._set_next_action(draft, next_action)\n            if outcome != "completed_internal_goal":\n                draft["claim"] = {\n                    "subject_kind": "none",\n                    "subject_id": None,\n                    "current_level": "none",\n                    "claim_ceiling": "none",\n                    "identity_bundle_object_id": None,\n                    "basis_receipt_ids": [],\n                    "blocked_by": [],\n                }\n''',
    )
    replace_once(
        operations,
        '''            draft["slice_budget"] = None\n            if outcome == "completed_pre_live_handoff":\n                draft["root_mission"]["status"] = "terminal"\n                draft["root_mission"]["terminal_outcome"] = outcome\n                draft["cursor"]["terminal_outcome"] = outcome\n            elif outcome in {"blocked_external", "stopped_by_user"}:\n                draft["root_mission"]["status"] = "terminal"\n                draft["root_mission"]["terminal_outcome"] = outcome\n                draft["cursor"]["terminal_outcome"] = outcome\n''',
        '''            draft["slice_budget"] = None\n''',
    )
    replace_once(
        operations,
        '''        return self.control.commit(\n            state["revision"],\n            idempotency_key,\n            mutate,\n            referenced_object_ids=[receipt_object_id, object_id],\n        )\n\n    def register_material_batch(\n''',
        '''        return self.control.commit(\n            state["revision"],\n            idempotency_key,\n            mutate,\n            referenced_object_ids=[receipt_object_id, object_id],\n            preserve_git_sync=True,\n        )\n\n    def register_material_batch(\n''',
    )

    replace_once(
        state_machine,
        '''terminal_outcomes:\n  - completed_pre_live_handoff\n  - closed_no_candidate\n  - blocked_external\n  - stopped_by_user\n''',
        '''internal_goal_outcomes:\n  - completed_internal_goal\n  - closed_no_candidate\n  - blocked_internal\n  - stopped_internal\nterminal_outcomes:\n  - completed_pre_live_handoff\n  - closed_no_candidate\n  - blocked_external\n  - stopped_by_user\n''',
    )
    replace_once(
        state_machine,
        '''  terminal_requires_git_sync: true\nstructured_action_required_fields:\n''',
        '''  internal_goal_close_may_set_root_terminal: false\n  root_terminal_transition_requires_root_closeout_object: true\n  root_closing_internal_outcome_preserves_claim_context: true\n  terminal_requires_git_sync: true\n  post_closeout_mutation_invalidates_git_sync: true\nstructured_action_kinds:\n  - none\n  - open_goal\n  - preregister_hypothesis\n  - open_stage\n  - declare_job\n  - run_job\n  - resume_job\n  - record_evidence\n  - close_goal\n  - close_root_mission\n  - repair\nstructured_action_required_fields:\n''',
    )

    print("Applied V2 P0 hardening. Review git diff before committing.")
    print("Focused tests:")
    print("  python -m unittest tests.v2.test_v21_state_operations")
    print("  python -m unittest tests.v2.test_v21_validation_git_cli")
    print("  python -m axiom_rift.v2.cli validate-surface --surface v2_1_harness")


if __name__ == "__main__":
    main()
