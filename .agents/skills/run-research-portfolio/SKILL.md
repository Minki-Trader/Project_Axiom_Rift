---
name: run-research-portfolio
description: Design and operate Axiom data, source, Portfolio, Study, Batch, Executable, Lineage, trial, evidence, candidate-library, synthesis, and negative-memory work. Use for quantitative or ML research, features, labels, models, trade logic, macro or external symbols, splits, causal tests, adaptive search, pruning, recombination, or next scientific direction.
---

# Run Research Portfolio

Read `contracts/science.yaml`, `contracts/evidence.yaml`, `foundation/data_exposure.yaml`, `foundation/prior_scientific_memory.yaml`, and the active Mission or Initiative record. Return evidence and a proposed Decision to the root operator; never edit canonical control state directly.

## Design

1. Maintain a broad Portfolio of unrelated questions and Lineages.
2. Choose the next axis by expected information value, causal identifiability, uncertainty, compute cost, and opportunity cost.
3. Do not select a default feature, label, model, objective, trade family, or external source.
4. Do not let a recent positive monopolize the Portfolio or a failure become a universal ban.
5. Use extremes, neighborhoods, ablations, boundary tests, and stresses when they clarify mechanism or surface shape.

## Register Before Evidence

- Define one causal question and the changed and controlled variables.
- Build an immutable Executable identity from ordered components, parameters, data, split, clock, cost, engine, and source semantics.
- Freeze an adaptive Batch bound, acceptance profile, compute/time limit, stop rule, and expected artifacts.
- Bind each Study to the current Portfolio snapshot, Decision, work-producing
  action, and immutable axis identity. Consume the Decision's finite Batch
  commitment mechanically at Batch entry.
- Bind Batch identity to the Study semantic hash and Batch semantics; display
  handles and names cannot reset a frozen budget.
- Count every unique evaluated Executable. Reuse identical success and reject unchanged failed retry.
- Start the same observed development material with the prior multiplicity floor in `foundation/data_exposure.yaml`, regardless of display name.
- Reject caller-invented material identities; display names or semantic aliases
  cannot reset the Foundation multiplicity floor.
- Query semantic prior warnings. Caller-created equivalence objects carry no
  authority; negative reuse remains closed until durable validated equivalence exists.

## Data And Sources

- Use completed bars and enforce availability at decision time.
- Keep fit, calibration, adaptive development, restricted confirmation, quarantine, and final forward evidence distinct.
- Require a one-time HoldoutPermit for scientific value access; sealed engineering ingestion reveals no value.
- Treat external data as executable input whenever it can change position intent.
- Allow performance evidence only after runtime eligibility and a valid SourcePermit.
- Persist each source edge through the writer with a typed, content-addressed
  eligibility receipt; arbitrary labels or empty source semantics are invalid.
- Bind every external-source Batch to its frozen `BatchSpec`, exact SourcePermit,
  and current source state. Suspension invalidates entry even after issuance.
- Fail a dependent sleeve closed on stale, missing, late, nonfinite, unsynchronized, or invalid mapping while independent sleeves remain operable.

## Disposition

Interpret causality, density, cost, economics, risk, stability, concentration, and evidence completeness non-compensatorily. Every material comparison retains at least one structurally diversifying action; a differently named adjacent DEEPEN target is not diversification. Record preserve, prune, deepen, rotate, contrast, recombine, or synthesize with the evidence scope, trial accounting, negative-memory scope and reopen condition, library update, and exact proposed next action.

Do not mutate a Portfolio while a Study or Batch is active. An axis ID cannot
change causal question or mechanism family inside a Mission. A
`closed_no_candidate` proposal requires a final snapshot with every declared
axis pruned, exact negative lineage, diverse family coverage, and no unresolved
candidate-eligible positive evidence.

At the initial Portfolio, preregister an adaptive exhaustion standard chosen
for that Mission. It must require at least three independent mechanism
families, multiple Studies per axis, multiple negative Executables per family,
and causal-contrast, sensitivity-or-stress, and cost-and-execution modes. A
later snapshot cannot lower it. Exhaustion credits only modes demonstrated by
the registered validator and retained in negative memory, never modes merely
listed in a Study question. Candidate disposition resolves positive
evidence only when it belongs to the same Mission, includes that completion,
and occurs afterward.

Derive each holdout dataset identity from its sealed artifact hash, its row
identity from artifact plus size, and its split identity from rows, time, and
predecessor. The same sealed bytes cannot be relabelled as later rows. A failed
holdout negative memory keeps the candidate's original trial Study and axis
lineage while binding the final holdout completion. After a reveal, pre-reveal
evidence cannot refreeze the invalidated Executable; wait for a durable future
development receipt bound to the successor holdout and post-receipt evidence.
Register that material only at the exact successor action. The receipt binds
verified content bytes, a post-predecessor/pre-successor time surface, split,
Mission, and current untouched successor without reading successor values.
Open later Studies only on the current registered material, and require a new
trial plus discovery and confirmation evidence after registration before freeze.

## Mandatory Study KPI Closeout

Closing a real Study strongly triggers one KPI checkpoint.  Pass
`StateWriter.close_study` the final Batch's disposition-driving,
validator-derived `stop_batch` completion whenever one exists.  If the final
Batch has no such completion, pass no completion: only the Writer may derive
an unavailable basis from an unstarted Batch, an exactly exhausted frozen
budget, an explicit early stop, or the final bound non-scientific failure.
Never pass caller-authored KPI numbers or unavailable prose, and never pick a
retrospective best result merely to populate the row.

The writer must create exactly one immutable `study-kpi` record and materialize
exactly one corresponding row in `records/STUDY_KPI.md`.  The row sequence is
global and monotonic, its time comes from the `study_closed` Journal event, its
Executable is subject-bound, and missing, invalid, censored, or inapplicable
metrics render as `-`, never zero or a pass.  The typed Study outcome is shown
without a display alias.  A stable collision-checked Executable display prefix
is assigned inside the immutable record while its full identity remains there;
the Markdown file is a Git observation projection rather than scientific
authority.

After closeout, return immediately to `$operate-axiom-mission` for the mandatory
local-main commit and immediate non-force `origin/main` push attempt.  Observe
remote equality when successful; retain same-commit delivery debt after a
bounded failure.  Do not continue directly to the next Portfolio action,
Study, Batch, or Job before the local checkpoint and first push attempt.
