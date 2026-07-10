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
3. The active V2 work unit, job, or receipt named by control state
4. Only the V2 contracts touched by the current action

Do not boot from V1 registries, campaigns, results, or archives.

## Root Mission

For a short `/goal`, continuation, next-work decision, H/S/R/P/M operation,
closeout, materialization, or blocker, read:

- `.agents/skills/axiom-v2-goal-operator/SKILL.md`

One user goal opens one persistent root mission. Internal goal, hypothesis, or
stage changes do not require another user prompt. A failed hypothesis does not
end the root mission. Continue until a contract-valid terminal outcome has a
clean metadata commit verified on `origin/main`.

Ask the user only for a scope change, destructive authority, live-capital
authority, a new credential or external-data permission, or a genuine external
blocker. Routine research, implementation, and stage decisions are autonomous.

An engineering-only reinforcement goal may end at `await_new_root_goal` without
opening a scientific root mission. At that boundary the active scientific
index, research map, trial references, negative memory, ingredients, and
candidates are empty, no holdout has been revealed, and no first H exists.

## Scientific Origin

- Future scientific work starts only from `registries/v2/scientific/index.yaml`.
- Bootstrap programs and engineering receipts are fixtures or provenance, not
  hypothesis seeds, positive evidence, negative evidence, or scheduler input.
- Active scientific surfaces must pass the V2 inheritance guard.
- External sources require runtime-data eligibility before feature use.
- H, S, and initial R are fixed-lot. Dynamic sizing is late-R evidence only and
  may not rescue failed fixed-lot economics.

## Active Boundaries

- Operate only on this PC, this repository, the current Python environment, and
  the current FPMarkets MT5 environment.
- FPMarkets US100 M5 is the project market target.
- The 5-to-10 entry target applies to the combined system per eligible day and
  is a target, not a quota.
- Discovery is fixed-lot; growth sizing is later evidence.
- V1 research, candidates, failures, and C0144 are legacy references only.
- V1 infrastructure is reusable only through a registered reuse decision.
- Claims may not exceed control state and durable receipts.
- No `live_ready` claim is allowed.
- Active project text is ASCII; Korean explanation belongs in chat.
- External review, PR approval, mandatory CI, portable deployment, and human
  intermediate reports are not completion requirements.

## Execution Boundaries

- Research code does not mutate active state.
- `src/axiom_rift/v2/operations.py` is the single state writer.
- Permit one active mutation or evidence job. Parallel state mutation is
  forbidden.
- The writer creates structured next actions; callers do not inject free-form
  transition commands.
- Every ordinary state mutation invalidates the prior Git checkpoint. A stored
  sync flag, `terminal_validation_pending`, or `terminal_pending_push` is not
  completion authority.
- Derive effective sync and terminal status read-only from a clean local HEAD,
  equal `origin/main`, and a metadata commit whose parent is the validated
  content commit. Do not create a third self-referential metadata commit.
- Resume a declared active job before creating another job.
- Work above 30 seconds is a declared bounded evidence job with input hashes,
  timeout, expected artifacts, logs, and a resume action.
- Routine validators are receipt checkers. They never build data, train,
  compile, export ONNX, run MT5, or download inputs.
- Consume validation, repair, and recheck budgets in code. Reuse an identical
  successful receipt and reject an identical failed retry.
- S has no MT5 requirement.
- S may route internally through breadth, depth, or synthesis evidence modes.
- A preregistered OAT sensitivity batch is part of one H, not a collection of
  adjacent H identities. Use at most two registered numeric knobs, baseline plus
  low/high, and one bounded local-calibration round.
- Fit on `train_is`, perform sensitivity and calibration on `validation_oos`,
  freeze one causal path per fold, and evaluate only that path on
  `development_cv`. Development-driven retuning is forbidden.
- Interpret KPI by non-compensatory dimensions. Missing or invalid KPI is a
  repair surface; censored or not-evaluable KPI never auto-passes.
- The 5-to-10 entry target is diagnostic for a sleeve and hard only for the
  combined system after exposure netting.
- Count every unique evaluated configuration and local candidate as a trial.
  An identical successful receipt cache hit is not another trial.
- Before a validation surface may choose a path, require causal checks, zero
  unknown-cost observations, and the preregistered per-fold trade minimum.
- Reconcile family and global trial hashes against durable prior receipts before
  H opens. A family rename or hypothesis-provided counter never resets history.
- Structural hold, horizon, stop, target, or lifecycle changes require a
  distinct registered program and H; they are not cheap local calibration.
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

Update durable objects and ledgers before control state. Keep one structured
next action and no undeclared active job. Validate one coherent changed surface,
then commit the declared milestone paths on local `main`, push `origin/main`,
and verify local and remote heads match. Root terminal state remains
`terminal_pending_push` until this read-only verification succeeds.

Commit and push H preregistration, evidence-stage closeout, candidate freeze,
complete blocker, and root terminal closeout. Do not validate, commit, or push
per file, artifact, fold, or micro-fix. A closeout is incomplete while its push
is unverified. Do not force-push, hard reset, auto-merge, auto-rebase, stage
unrelated paths, or discard unrelated work.
