---
name: run-research-portfolio
description: Direct Axiom quantitative research from Mission intake through history audit, hypothesis-axis Portfolio design, baseline Study execution, evidence diagnosis, constrained follow-up, architecture saturation review, candidate synthesis, and negative memory. Use for record_research_intake, build_portfolio, portfolio_decision, execute_portfolio_decision, diagnose_study, review_architecture, or any data, source, feature, label, model, calibration, selector, trade, lifecycle, risk, execution, Study, Batch, Executable, Lineage, evidence, candidate, synthesis, or next-scientific-direction work.
---

# Run Research Portfolio

Read `contracts/science.yaml`, `contracts/evidence.yaml`,
`foundation/data_exposure.yaml`, `foundation/prior_scientific_memory.yaml`, and
the active Mission or Initiative record. Return typed research records,
evidence, and a proposed Decision to `$operate-axiom-mission`. Never edit
canonical control state directly.

Read `references/research-direction.md` whenever the exact next action is
`record_research_intake`, `build_portfolio`, `diagnose_study`, or
`review_architecture`, or when selecting a result-driven follow-up.

## Hierarchical Stage Router

Treat `state/control.json.next_action` as the stage trigger. Prompt wording
cannot skip a stage.

| Exact trigger | Research role | Required output |
| --- | --- | --- |
| `record_research_intake` | research director | `MissionResearchIntake` |
| `build_portfolio` | hypothesis portfolio lead | intake-bound `PortfolioSnapshot` |
| `portfolio_decision` | research allocator | `PortfolioDecision` |
| `execute_portfolio_decision` | Study lead | preregistered Study and Batch proposal |
| `diagnose_study` | evidence diagnostician | `StudyDiagnosis` |
| `review_architecture` | system research lead | `ArchitectureReview` |
| candidate or synthesis action | portfolio and candidate lead | subject-bound candidate proposal |

The research director owns sequencing and opportunity cost. Feature, label,
model, calibration, trade, lifecycle, risk, execution, and portfolio lenses
are specialists selected by diagnosed need, not calendar rotation.

## Mission Research Intake

Before the first Initiative of every real Mission:

1. Bind the intake to the exact current Journal head.
2. Run
   `.agents/skills/run-research-portfolio/scripts/audit_research_history.py`
   with `--root . --summary-only`, then use `--study-id` or the full output for
   the material surfaces. Its output is a read-only map, not authority.
3. Review Study KPI, Study questions, validator evidence, negative memory,
   Portfolio Decisions, Executable components, and Mission terminals.
4. Treat `records/STUDY_KPI.md` as a navigation projection, never scientific
   authority or a retrospective winner table.
5. Map prior work by causal question, primary research layer, architecture
   family, changed and controlled domains, outcome, evidence state, and reopen
   condition. Mark legacy work honestly when typed classification is absent.
6. State at least two competing bottleneck hypotheses, underexplored layers,
   architecture findings, and one Mission thesis.

Do not open an Initiative or choose an axis before the writer accepts the
intake. Do not invent historical counts; the writer derives the compact
history summary from the durable index.

## Portfolio And Axis Design

Maintain unrelated causal axes and compare expected information value,
identifiability, uncertainty, compute cost, and opportunity cost.

Every axis declares one immutable primary `ResearchLayer`, one stable
`system_architecture_family`, typed changed and controlled domains, `why_now`,
and a stop or reopen condition. A non-synthesis axis changes exactly its one
primary layer. Synthesis or Portfolio axes may change multiple domains but must
say so explicitly.

The initial intake-bound Portfolio preregisters immutable exhaustion and
architecture-review thresholds. It must be diverse in mechanism family,
primary research layer, and architecture family. This is a terminal-credibility
standard, not a quota requiring periodic layer rotation.

Do not select a default feature, label, model, objective, trade family, or
external source. Do not let a recent positive monopolize the Portfolio or a
failure become a universal ban. Use extremes, neighborhoods, ablations,
boundary tests, and stress when they identify a mechanism or surface.

## Register Before Evidence

- Define one causal question and explicit changed and controlled variables.
- Bind the Study to the current intake, Portfolio snapshot, axis identity,
  Decision, and immutable development material.
- Build Executable identity from ordered components, parameters, data, split,
  clock, cost, engine, and source semantics.
- Freeze an adaptive Batch bound, acceptance profile, compute and wall limits,
  stop rule, expected artifacts, and evidence modes.
- Consume the Decision's finite Batch commitment mechanically.
- Count each unique Executable. Reuse identical success and reject unchanged
  failed retry.
- Query semantic warnings; a caller-created equivalence object is not authority.

Prefer the smallest interpretable baseline contrast that can falsify the
question. Hold the common chassis fixed and change the declared primary layer.
Do not hide a multi-layer redesign inside a feature-named Study.

## Data And Sources

Use completed bars and enforce feature and external availability at decision
time. Keep fit, calibration, development, restricted confirmation, quarantine,
and final forward evidence distinct. Require one-time HoldoutPermit for value
access; sealed ingestion exposes no values.

Treat every inference-time external dependency as executable input. Performance
requires runtime eligibility, an exact SourcePermit, and current source state.
Fail stale, missing, late, nonfinite, unsynchronized, or invalid mappings closed
for the dependent sleeve without stopping independent sleeves.

After a holdout reveal, never retune or refreeze from pre-reveal evidence.
Require a registered later development receipt and new post-registration
discovery and confirmation evidence before another candidate freeze.

## Study Diagnosis And Follow-Up

Every real Study close first completes its mandatory local-main checkpoint and
push attempt. Then satisfy the exact `diagnose_study` action.

Bind `StudyDiagnosis` to the exact close, final Batch, KPI basis, validator
completion when present, and negative memory when present. Classify the
evidence state, confidence, counterfactual, and reopen condition. KPI magnitude
alone cannot choose the state. Engineering failure is `engineering_gap`, not
scientific falsification.

The writer derives allowed local actions and research-layer branches from the
typed evidence state. The next Decision must either follow that branch,
dispose the diagnosed axis consistently, or make a genuinely structural forest
exit to a different layer or architecture. Adjacent same-chassis tuning is not
a structural exit.

## Architecture Review

When preregistered repeated gaps or negatives accumulate across enough Studies
and distinct axes under one architecture family, the writer emits
`review_architecture`. No Initiative close, Portfolio Decision, Study, Batch,
or Job may bypass it.

Bind `ArchitectureReview` to the exact `trigger_record_id`; this keeps repeated
reviews of one architecture distinct and binds each conclusion to its covered
diagnosis set.

Choose one typed conclusion:

- `change_research_layer`: require the next selected or newly admitted axis to
  leave the reviewed layers.
- `rotate_architecture`: require the next selected or newly admitted axis to
  leave the reviewed architecture family.

The review is a scheduler and identifiability decision, not negative evidence.
It consumes only its exact unreviewed diagnosis set, so later genuinely new
evidence can trigger another bounded review.

## Disposition And Terminal Scope

Interpret causality, density, cost, economics, risk, stability, concentration,
and completeness non-compensatorily. Material Decisions retain at least one
structurally diversifying option and record omission reasons. Record preserve,
prune, deepen, rotate, contrast, new mechanism, complementary sleeve,
recombine, or synthesize with exact evidence scope and next action.

Do not mutate a Portfolio while a Study or Batch is active. Axis meaning is
immutable inside a Mission. A `closed_no_candidate` proposal requires every
axis pruned, exact negative lineage, the preregistered mechanism, research-layer,
architecture, Study, Executable, and validator-demonstrated evidence depth,
plus no unresolved candidate-eligible positive evidence.

## Mandatory Study KPI And User Report

Pass `StateWriter.close_study` only the final disposition-driving validator
`stop_batch` completion when one exists. Otherwise pass no completion and let
the writer derive the typed unavailable basis. Never pass caller-authored KPI,
unavailable prose, or a retrospective best result.

The writer creates one immutable `study-kpi` record and one deterministic row
in `records/STUDY_KPI.md`. Missing, invalid, censored, or inapplicable values
render as `-`, never zero or pass.

At each Study close, explain in Korean chat:

- the causal hypothesis and primary research layer;
- the architecture family and what stayed controlled;
- the typed outcome and evidence-state interpretation;
- net profit, profit factor, trades, and drawdown share, preserving `-`;
- the exact follow-up or stop/reopen condition.

Return to `$operate-axiom-mission` for the required Study-close commit and push
before diagnosis or later scientific work.
