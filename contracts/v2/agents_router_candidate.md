# AGENTS

schema: axiom_rift_agent_rules_v2_active
project_id: project_axiom_rift
audience: codex_only
active_truth: v2
active_text_encoding: ascii_only
human_friendly_text_policy: chat_only

## Boot

Read in order:

1. `AGENTS.md`
2. `registries/v2/control_state.yaml`
3. Active V2 work unit or receipt named by control state
4. Only V2 contracts touched by the task

Do not boot from V1 registries, campaigns, results, or archives.

## Goal Operation

For a short `/goal`, continuation, next-work decision, H/S/R/P/M operation,
closeout, materialization, or blocker, read:

- `.agents/skills/axiom-v2-goal-operator/SKILL.md`

Short goals inherit `contracts/v2/`. One logical research goal continues across
stage changes without another user goal.

## Active Boundaries

- FPMarkets US100 M5 is the project market target.
- The 5-to-10 entry target applies to the combined system per eligible day.
- Discovery is fixed-lot; growth sizing is later evidence.
- V1 research, candidates, failures, and C0144 are legacy references only.
- V1 infrastructure is reusable only through a registered reuse decision.
- Claims may not exceed `registries/v2/control_state.yaml` and durable receipts.
- No `live_ready` claim is allowed.
- Active project text is ASCII; Korean explanation belongs in chat.

## Execution Boundaries

- Research code does not mutate active state.
- `src/axiom_rift/v2/operations.py` is the single state writer.
- Routine validators never build data, train, compile, export ONNX, run MT5, or
  download inputs.
- Work above 30 seconds is a declared bounded evidence job.
- S has no MT5 requirement.
- Full isolated nine-fold MT5 is limited to P, recertification, or a recorded
  partition-equivalence failure.
- Zero spread is unknown cost, not free execution.
- Broken code is repaired or recorded as a blocker, never hypothesis evidence.
- Failures become durable negative memory or parity/execution lessons.

## Canonical Paths

- source: `src/axiom_rift/v2/`
- contracts: `contracts/v2/`
- configs: `configs/v2/`
- state and ledgers: `registries/v2/`
- work units: `campaigns/v2/`
- tests: `tests/v2/`

V1 paths remain immutable legacy references unless an explicit migration task
names them.

## Closeout

Update durable objects and ledgers before control state. Keep one exact next
action and no undeclared active job. Validate the changed surface, commit a
coherent milestone on local `main`, and push `origin/main`. Do not force-push,
hard reset, or discard unrelated work.
