# V2 P0 Hardening Review

## Scope

This draft PR contains a fail-closed applicator for two P0 harness issues found in the latest V2 review.

1. Internal-goal closeout can currently set the root mission terminal without passing the strict `close_root_mission()` checks.
2. A previously recorded `git_sync.status: synced` can remain present after later state mutations, allowing stale synchronization evidence to satisfy a holdout or terminal gate.

No research model, feature, selector, MT5 logic, V2H0002 hypothesis, data file, ledger, or active control state is modified by this PR as submitted.

## Why an applicator is used

The connector used to prepare this PR can create and replace complete GitHub files but cannot submit a line-oriented patch directly. Replacing the 2,000-line state writer without executing the repository tests would be unnecessarily risky.

`tools/apply_v2_p0_hardening.py` therefore:

- verifies every reviewed source snippet occurs exactly once;
- aborts before writing if `main` has drifted from the reviewed source;
- performs only deterministic text replacements;
- leaves the resulting source diff uncommitted for Codex review;
- prints the focused test commands required before closeout.

## Intended source changes

### Root terminal path

- Separate internal-goal outcomes from root terminal outcomes.
- Add `close_root_mission` to structured action kinds.
- Prevent `close_goal()` from changing `root_mission.status` or `terminal_outcome`.
- Preserve claim context only for `completed_internal_goal`, so strict success checks remain possible in `close_root_mission()`.
- Keep `closed_no_candidate`, external blocker, and user-stop root decisions in the dedicated root closeout path.

### Git synchronization freshness

- Add `preserve_git_sync=False` to `ControlStore.commit()`.
- Invalidate prior Git synchronization evidence after every ordinary V2 state mutation.
- Preserve synchronization only while recording a verified Git closeout and while creating the root terminal closeout from already-synchronized evidence.
- As a result, candidate freeze or any later mutation must be followed by a fresh verified `origin/main` closeout before holdout authorization.

## Required Codex review procedure

```text
python tools/apply_v2_p0_hardening.py
git diff --check
git diff -- src/axiom_rift/v2/state/transitions.py
git diff -- src/axiom_rift/v2/state/store.py
git diff -- src/axiom_rift/v2/operations.py
git diff -- contracts/v2/state_machine.yaml
```

Codex should reject the patch if the script aborts because a reviewed snippet differs. Do not weaken the snippet guards to force application; re-review the current source instead.

## Focused validation after application

```text
python -m unittest tests.v2.test_v21_state_operations
python -m unittest tests.v2.test_v21_validation_git_cli
python -m axiom_rift.v2.cli validate-surface --surface v2_1_harness
```

Add explicit regression tests before merging:

- `close_goal(outcome="completed_pre_live_handoff")` is rejected as an invalid internal outcome.
- `close_goal(outcome="blocked_external")` is rejected as an invalid internal outcome.
- `completed_internal_goal` does not set root terminal and preserves the current claim.
- Only `close_root_mission()` may set root terminal.
- A normal mutation changes Git sync from `synced` to `unsynced`.
- `record_git_closeout()` restores `synced`.
- Holdout permit issuance fails after candidate/state mutation until a fresh closeout is recorded.
- Root terminal closeout fails when Git sync is stale.

## Merge boundary

This patch should be applied and validated before opening V2G0002. It should remain a harness-only change with claim ceiling `none` and must not create economic evidence.
