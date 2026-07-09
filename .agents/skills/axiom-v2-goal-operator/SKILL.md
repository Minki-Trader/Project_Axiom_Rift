---
name: axiom-v2-goal-operator
description: Operate Project Axiom Rift V2 from a short goal or continuation prompt through the H/S/R/P/M lifecycle, including preregistration, bounded evidence jobs, claim-safe transitions, negative memory, ONNX/EA materialization, activation, reentry, and git closeout. Use for Axiom V2 next-work decisions, stage changes, scout or confirmation runs, promotion, materialization, blockers, closeouts, or resuming an active job.
---

# Axiom V2 Goal Operator

## Boot

Read in this order:

1. `AGENTS.md`.
2. `registries/v2/control_state.yaml`.
3. The active work unit and receipt named by control state.
4. Only the V2 contracts governing the requested stage.

Do not boot from V1 registries, campaigns, results, or archive files.

## Resume Before Starting

If `reentry.active_job` is non-null, inspect its declared artifacts and resume or
close that exact job. Do not create a replacement run or repeat an unchanged
successful receipt.

Keep one exact next action. The single writer in
`src/axiom_rift/v2/operations.py` owns active objects, ledgers, and control-state
mutation. Research code returns results and must not mutate registries.

## Classify the Operation

Classify the next action as one of:

- true hypothesis or program variant
- repair of broken code or evidence plumbing
- stage closeout or negative-memory synthesis
- engine recertification
- pause or genuine external blocker

Reject adjacent threshold, window, stop, target, or retry-only changes presented
as a new research axis.

## H/S/R/P/M Flow

### H - Hypothesis

Preregister the question, executable component identities, split roles,
falsification, frozen acceptance profile, novelty, portability, evidence budget,
and claim ceiling. Check V1 only after preregistration and only for mechanical
duplication or implementation hazards.

### S - Scout

Use only preregistered representative development anchors. Enforce causal
features, fold-isolated fit and calibration, sequential admission, unknown-cost
handling, activity across all eligible days, and boundary purge. Do not run MT5
or isolated nine-fold validation. Close weak results as diagnostic negative
memory.

### R - Confirmation

Open R only from a surviving S receipt. Use all required development folds,
uncertainty, trial accounting, and minimal certified MT5 confirmation. When a
valid conformance receipt applies, default to one aggregate closed-bar run and
one aggregate real-tick run, then partition only under proven boundary
equivalence.

### P - Promotion

Reserve full isolated nine-fold MT5 for promotion, engine recertification, or a
recorded partition-equivalence failure. Freeze the candidate before holdout
access. Require realistic cost stress, stability, drawdown, exposure, and
multiple-testing evidence before stronger claims.

### M - Materialization

Enter only with a selected frozen identity. Export ONNX, integrate native online
EA inference, and prove parity in contract order. Produce the hashed pre-live
handoff. Do not create `live_ready`.

Continue one logical goal across stage changes. End only as
`completed_pre_live_handoff`, `closed_no_candidate`, `blocked_external`, or
`stopped_by_user`.

## Validation Economics

Routine validators are receipt checkers only. Target 3-15 seconds and fail at 30
seconds. They must not build data, train, compile, export ONNX, launch MT5, or
download inputs.

For one coherent slice use one implementation batch, one focused validation
batch, at most one consolidated repair, and one focused recheck. A repeated
failure requires root-cause boundary redesign, component replacement, or a
complete blocker.

Declare work expected above 30 seconds as a bounded evidence job with input
hashes, timeout, logs, expected artifacts, and a resume boundary.

## Claims and Failures

Use the scalar claim ladder in `contracts/v2/claim_ladder.yaml`. Never infer a
stronger claim from aggregate profit, development CV, an ONNX file, compilation,
schedule replay, or missing KPI.

Broken code is repair evidence, not hypothesis evidence. Record a failed valid
hypothesis as negative memory, parity lesson, execution-divergence lesson,
evidence gap, or non-portable lesson.

## Closeout

Update control state only after durable objects and ledger rows exist. Record
receipt IDs, artifact hashes, no active job, remaining budgets, and one exact
next action. Validate the changed surface, commit a coherent milestone on local
`main`, and push `origin/main`. Never force-push, reset, or discard unrelated
work.
