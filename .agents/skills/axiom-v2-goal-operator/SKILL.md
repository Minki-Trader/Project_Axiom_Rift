---
name: axiom-v2-goal-operator
description: Operate one persistent Project Axiom Rift V2 root mission from a single user goal through repeated H/S/R/P/M cycles, bounded evidence jobs, automatic failed-hypothesis continuation, claim-safe transitions, negative memory, ONNX/EA materialization, reentry, and required main-to-origin Git closeout. Use for V2 goal start or continuation, next-work decisions, stage changes, scout or confirmation runs, promotion, materialization, blockers, closeouts, or active-job resume.
---

# Axiom V2 Goal Operator

## Boot

Read in order:

1. `AGENTS.md`.
2. `registries/v2/control_state.yaml`.
3. The active work unit, job, or receipt named by control state.
4. Only the V2 contracts governing the structured next action.

Do not boot from V1 registries, campaigns, results, or archives.

## Persist the Root Mission

Treat one user goal as one root mission until a terminal outcome exists. Internal
goal, hypothesis, and stage IDs may change without another user prompt. A failed
hypothesis closes only that hypothesis; it never closes the root mission.

Ask the user only for a scope change, destructive authority, live-capital
authority, a new credential or external-data permission, or a genuine external
blocker. Make routine research, implementation, and transition decisions
autonomously.

Allowed root outcomes are `completed_pre_live_handoff`,
`closed_no_candidate`, `blocked_external`, and `stopped_by_user`.
`completed_pre_live_handoff` means a verified local-machine pre-live bundle.

## Run the Bounded Loop

While no root outcome exists:

1. Load and validate control state and Git preconditions.
2. Resume the declared active job, if any.
3. Otherwise execute or materialize the structured next action.
4. Write immutable objects and ledger rows before control state.
5. Run one focused close validator for the coherent slice.
6. Commit only declared milestone paths on local `main`.
7. Push `origin/main` and verify local and remote heads match.
8. Transition state and continue immediately.

Use bounded steps with durable reentry. Do not create a daemon, workflow DAG,
or unbounded shell process. Codex supplies high-dimensional hypothesis judgment;
the harness supplies deterministic guards and state transitions.

## Resume Before Starting

If `active_job` is non-null, inspect its declared artifacts and resume, close,
or block that exact job. Do not create a replacement job or repeat an unchanged
successful receipt. Clear an active job only when the receipt matches its job,
stage, input identity, and expected artifacts.

Keep one structured next action. The single writer in
`src/axiom_rift/v2/operations.py` owns active objects, ledgers, budgets, and
control-state mutation. Research code returns results and never mutates state.

## Classify Work

Classify the next action as:

- true structural hypothesis or registered numeric sensitivity work
- broken-code or evidence-plumbing repair
- stage closeout or negative-memory synthesis
- engine recertification
- pause or genuine external blocker

Reject unregistered adjacent or retry-only changes presented as new research
axes. Keep preregistered low/base/high numeric sensitivity inside one H. Treat
hold, label horizon, stop, target, or lifecycle changes as distinct registered
programs and H identities rather than cheap local calibration.

## H/S/R/P/M

### H - Hypothesis

Preregister the question, executable component identities, split roles,
falsification, frozen acceptance profile, novelty, evidence budget, and claim
ceiling. Resolve KPI rules, exact thresholds, sensitivity ranges, local
calibration rule, trial cap, and selection tie-breaks before results. Permit at
most two registered numeric knobs, baseline plus low/high, no Cartesian grid,
and one local-calibration round. Validate schema and identity only, then commit
and push before S.

### S - Scout

For every outer fold, fit on `train_is`, evaluate the preregistered OAT
low/base/high surface on `validation_oos`, optionally execute one deterministic
strictly interior local calibration on that same validation role, freeze one
causal operating path, and evaluate exactly that path on `development_cv`.
Never select among development variants or retune from development results.
Do not run MT5 or isolated nine-fold validation. On rejection or scale miss,
record scoped negative memory and disposition; validate once, commit and push,
select the next high-information structural axis, preregister the next H, and
continue.

### R - Confirmation

Open R only from a surviving S receipt. Freeze R inputs and push them before the
evidence job. Use all development folds, uncertainty, trial accounting, and the
minimum certified MT5 confirmation. Prefer one aggregate closed-bar and one
aggregate real-tick run with receipt-backed partitioning.

### P - Promotion

Reserve isolated nine-fold MT5 for promotion, recertification, or recorded
partition-equivalence failure. Freeze candidate identity and verify its commit
on `origin/main` before the single permitted holdout reveal.

### M - Materialization

Enter only with a selected frozen identity. Export ONNX, integrate native online
EA inference, prove required parity and lifecycle recovery, and create the hashed
local pre-live bundle. Never create `live_ready`.

Build real R, P, and M adapters only when a candidate reaches their gates. Keep
their deterministic transition guards available earlier.

## Validation Economics

Routine validators are receipt checkers only. Target 3-15 seconds and fail at 30
seconds. Never let them build data, train, compile, export ONNX, launch MT5, or
download inputs.

Consume one implementation, validation, repair, and recheck budget per coherent
slice. An identical successful validation is a cache hit and spends no budget.
Reject an identical failed retry. After one consolidated repair and recheck,
redesign the boundary, replace the component, or record a complete blocker.

Declare work expected above 30 seconds as a bounded evidence job with exact
command, input hashes, timeout, logs, expected artifacts, claim ceiling, and
resume action.

## KPI and Parameter Governance

Interpret KPI in non-compensatory order: integrity, inferential density,
activity, economics, risk, stability, execution, then portfolio fit. Never hide
a failed hard dimension inside a weighted score. Missing or invalid required KPI
is repair evidence, not hypothesis failure. Censored or not-evaluable KPI never
auto-passes. Treat five-to-ten entries as a combined-system target; a sparse but
complementary sleeve is not rejected solely for missing that band.

Use sensitivity to classify a registered numeric surface as plateau, needle,
boundary trend, unstable, or weak. Freeze a passing baseline on a plateau. Run
one preregistered local calibration only for a bracketed plateau. Do not locally
calibrate a needle, boundary hit, unstable surface, structural trade parameter,
frozen candidate, or holdout-informed design. A boundary trend may justify one
distinct H with a new preregistered range; it never authorizes automatic range
extension.

Count every unique executable baseline, extreme, and local candidate as a
trial. Count variant-by-fold work separately as evaluation cells. A cache hit of
the same successful hash is not another trial; code failure before metrics is an
execution failure, not a scientific trial. Incomplete trial accounting blocks
`research_candidate` and stronger claims.

Do not let a primary sensitivity KPI choose by itself. Each validation-fold
candidate must first pass the preregistered feasibility floor: causal checks,
zero unknown-cost observations, and minimum evaluable trades. Reconcile the
family and global configuration lists and their history hashes against durable
prior receipts before preregistration. Renaming a family never resets a global
trial. Count identical executable configurations once across folds while
counting their fold evaluation cells separately.

## Claims and Exhaustion

Use `contracts/v2/claim_ladder.yaml`. Never infer a stronger claim from
aggregate profit, development CV, an ONNX file, compilation, schedule replay,
or missing KPI.

Broken code is repair evidence, not hypothesis evidence. Preserve valid failures
as negative memory, parity lessons, execution-divergence lessons, evidence gaps,
or non-portable lessons.

Close a root mission as `closed_no_candidate` only after the frozen mission
budget is exhausted or every remaining causal axis has low expected information
value, is directly contradicted by scoped negative memory, requires holdout
reuse, or consists only of exhausted or forbidden local tuning.

## Git Closeout

Use Git as the remote evidence checkpoint, not as a review workflow. Commit and
push H preregistration, evidence-stage closeout, candidate freeze, complete
blocker, and root terminal closeout. Do not commit or push per file, artifact,
fold, or micro-fix.

Stage declared paths only. Do not use `git add -A`, force-push, hard reset,
auto-merge, auto-rebase, or discard unrelated work. A push failure never reruns
scientific validation. Retry one safe identical commit at most once after
diagnosis; otherwise record `blocked_external` with the local commit and exact
resume command.
