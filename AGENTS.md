# AGENTS

schema: axiom_agent_router
audience: codex_only
encoding: ascii_only
authority: OPERATING_DIRECTION.md

## Boot

Read in this order:

1. `OPERATING_DIRECTION.md`
2. `state/control.json`
3. The active record named by control state, or the predecessor terminal named
   by the Mission-admission boundary
4. The required repo skill route selected below
5. Only the contracts and Foundation inputs touched by the action

The repository is sufficient. Do not require chat history or removed project
state.

## Trigger Router

- Use `.agents/skills/operate-axiom-mission/SKILL.md` for `/goal`, Project Goal,
  first or successor Mission admission, initiative operation, continuation,
  next action, Job, Repair, blocker, terminal, state mutation, reentry,
  closeout, or Git observation.
- Use `.agents/skills/run-research-portfolio/SKILL.md` for data, time, split,
  source eligibility, feature, label, model, trade, Study, Batch, Executable,
  Lineage, trial, evidence, Portfolio, candidate, synthesis, or negative memory.
- Use `.agents/skills/prove-runtime-release/SKILL.md` for ONNX, MQL5, MQH, EA,
  MT5, parity, execution proof, materialization, recertification, or Release.

When triggers overlap, route through the Mission skill, then the domain skill,
then back to the single state writer for the Decision and transition.

## Mechanical Boundaries

- `axiom_rift.operations.writer.StateWriter` is the only control-state writer.
- Treat `OPERATING_DIRECTION.md` as the persistent Project Goal and keep at
  most one active Mission. A bare or one-line `/goal` resumes it, or admits a
  successor only through the exact predecessor-bound Mission boundary.
- Research, evidence, runtime, and validation code never edit state directly.
- Require typed permits at engine boundaries; prompts are not capabilities.
- Resume an active Job or Repair before opening another.
- Keep one exact structured next action at stable boundaries.
- Use the durable journal as authority and the local SQLite index as a
  reconstructible projection.
- Count trials and claims by immutable Executable identity, never display name.
- Treat engineering failure as Repair evidence, not scientific evidence.
- Never read quarantined or holdout values without the required permit.
- Never create live or live-ready authority.
- Only `completed_pre_live_handoff` completes the API Goal. A valid negative
  Mission terminal continues through its bound successor; a genuine external
  blocker waits for its exact resume condition.

## Local Boundary

Operate only on this repository, this PC, the current Python environment, and
the current FPMarkets MT5 environment. Protected ignored data under `data/`
must not be removed. Project text is ASCII; explain to the user in Korean chat.
External review, PR approval, CI, cloud, VPS, portability, and another-PC
support are not completion requirements.

## Verification And Closeout

Use focused checks for the changed reusable surface. Do not require a full test
suite or rerun evidence inside a validator. Commit and push coherent
milestones, not files or micro-fixes. Git is delivery observation, not
scientific authority. Do not force-push, hard reset, rewrite history, stage
unrelated paths, or clean outside a verified allowlist.
