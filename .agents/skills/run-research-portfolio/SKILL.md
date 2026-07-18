---
name: run-research-portfolio
description: Direct Axiom quantitative research from Mission intake through history audit, effective-axis and replay-obligation handling, hypothesis-axis Portfolio design, baseline Study execution, evidence-bound Study continuation, atomic evidence diagnosis, constrained follow-up, architecture saturation review, candidate synthesis, and negative memory. Use for record_research_intake, build_portfolio, portfolio_decision, execute_portfolio_decision, review_study_continuation, diagnose_study, review_architecture, or any data, source, feature, label, model, calibration, selector, trade, lifecycle, risk, execution, Study, Batch, Executable, Lineage, evidence, candidate, synthesis, or next-scientific-direction work.
---

# Run Research Portfolio

Read `contracts/science.yaml`, `contracts/evidence.yaml`,
`foundation/data_exposure.yaml`, `foundation/prior_scientific_memory.yaml`, and
the active Mission or Initiative record. Return typed research records,
evidence, and a proposed Decision to `$operate-axiom-mission`. Never edit
canonical control state directly.

Read `references/research-direction.md` whenever the exact next action is
`record_research_intake`, `build_portfolio`, `review_study_continuation`,
`diagnose_study`, or `review_architecture`, or when selecting a result-driven
follow-up.

## Hierarchical Stage Router

Treat `state/control.json.next_action` as the stage trigger. Prompt wording
cannot skip a stage.

| Exact trigger | Research role | Required output |
| --- | --- | --- |
| `record_research_intake` | research director | `MissionResearchIntake` |
| `build_portfolio` | hypothesis portfolio lead | intake-bound `PortfolioSnapshot` |
| `portfolio_decision` | research allocator | `PortfolioDecision` |
| `execute_portfolio_decision` | Study lead | preregistered Study and Batch proposal |
| `review_study_continuation` | Study and portfolio leads | `StudyContinuationDecision` |
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
5. Map prior work by exact semantic question core, typed Study lineage, primary
   research layer, architecture family, outcome, evidence state, and reopen
   condition. Give every repeated exact core a relation or an explicit
   unresolved disposition. Mark legacy work honestly when typed classification
   is absent.
6. State at least two competing bottleneck hypotheses, underexplored layers,
   architecture findings, and one Mission thesis.

Do not open an Initiative or choose an axis before the writer accepts the
intake. Do not invent historical counts; the writer derives the compact
history summary from the durable index.

## Portfolio And Axis Design

Maintain unrelated causal axes and compare expected information value,
identifiability, uncertainty, compute cost, and opportunity cost.

Use plural quant-team lenses for causality, statistics, data, execution,
economics, risk, and architecture. Record material disagreement at the claim
boundary and resolve it with evidence and opportunity cost. Do not collapse the
Decision into one universal scalar score, rigid calendar rotation, or a serial
single-branch policy. The harness enforces permits, identity, budgets, and claim
scope; the research director retains bounded autonomous judgment.

For every new material Portfolio Decision, attach one typed
`QuantTeamDecisionReview`. Use only the lenses that are material, but require at
least two distinct lenses to assess the chosen allocation and cover every
compared option. Bind findings to the current Portfolio snapshot and to the
exact Study diagnosis, replay obligation, or architecture review when one
constrains the action. A challenge or uncertainty needs an explicit resolution
and claim boundary. This is a compact decision record, not seven role reports.

At every generic Portfolio boundary, query the authenticated effective-axis
action matrix before designing work. `selectable` means the axis is not blocked;
it is not permission to repeat any action. Apply the latest effective diagnosis
for that exact axis, and when it was corrected bind the original diagnosis,
correction, and audit in the quant-team review. Do not spend design time on an
action absent from the matrix. An exact typed ArchitectureReview continuation
or replay constraint uses its own bounded authority and is not a free-form
escape from, or silently vetoed by, the generic matrix.

When the exact next action carries `post_holdout_development_id`, cite that
durable authority in the quant-team review. Preserve it through any authorized
structural Portfolio snapshot mutation, then bind the scientific Decision and
Study to its exact material, data contract, split contract, and still-sealed
successor Holdout. An older axis diagnosis cannot veto genuinely later
registered material, but the material authority is not permission for an
unrelated action or an unbound baseline. Preserve any exact replay scheduler
constraints across registration and Initiative admission; later material does
not erase a pending replay obligation.

Before admitting replay work, classify its structural effect exactly once.
`reuse_exact_axis` requires the same axis identity, semantic core, mechanism,
and chassis and creates no Portfolio Decision or snapshot. `revise_protocol`
keeps the logical axis ID, mechanism, and semantic core, but replaces its exact
chassis and identity under a typed current invalidation while preserving the
axis count and every unrelated axis. `add_new_mechanism` is reserved for a
genuinely absent mechanism family and adds one axis. Never relabel a mechanism
to evade the duplicate-family guard. An accepted but unstarted structural
misclassification is withdrawn only by its evidence-bound additive Writer
transition before the corrected classification is admitted.

Treat a replay runner operation prefix as one-shot after its exact `open-study`
operation binds a natural Study. A later request naming another Study receives
only the recorded owner handoff and cannot execute a stage. Resume the bound
Study, or give a genuine successor protocol a distinct operation prefix; never
reuse a completed prefix and reinterpret an idempotent result as new work.

Every axis declares one immutable primary `ResearchLayer`, one stable
`system_architecture_family`, typed changed and controlled domains, `why_now`,
and a stop or reopen condition. A non-synthesis axis changes exactly its one
primary layer. Synthesis or Portfolio axes may change multiple domains but must
say so explicitly.

The initial intake-bound Portfolio preregisters evidence-bound exhaustion and
architecture-review thresholds. It must be diverse in mechanism family,
primary research layer, and architecture family. This is a terminal-credibility
standard, not a quota requiring periodic layer rotation. Its numeric floors and
required evidence modes remain immutable inside the Mission. Additive evidence
may qualify conclusions without rewriting the standard. If a later exhaustive
audit proves the standard itself defective, bind that finding into the exact
successor Mission intake and its newly preregistered standard; never reinterpret
history silently.

Do not select a default feature, label, model, objective, trade family, or
external source. Do not let a recent positive monopolize the Portfolio or a
failure become a universal ban. Use extremes, neighborhoods, ablations,
boundary tests, and stress when they identify a mechanism or surface.

When several live axes share one data and decision boundary, prefer one
preregistered concurrent forest to serial one-axis Decisions. Freeze the exact
family and common calendar, run axes together when their resource claims are
disjoint, and preserve synchronized selection inference. Compare information
value, identifiability, compute cost, architecture, and opportunity cost before
deepening, contrasting, recombining, or pruning. Never add missing family days
as implicit zero PnL.

## Register Before Evidence

- Define one causal question and explicit changed and controlled variables.
- Let the Writer derive its exact semantic question core. A repeated exact core
  requires typed predecessor lineage. A non-revision relation between distinct
  cores requires accepted expert-reviewed equivalence; a semantic revision must
  remain distinct and non-equivalent.
- Treat equivalence as question-core scope only. It never transfers or merges
  Study, Batch, Executable, trial, evidence, claim, KPI, negative-memory, or
  multiplicity authority, and it is never inferred from fuzzy text similarity.
- Bind historical reconciliation to the exact current-protocol audit artifact
  carrying the plural quant-team review; caller rationale alone is not review
  authority.
- Bind the Study to the current intake, Portfolio snapshot, axis identity,
  Decision, and immutable development material.
- Build Executable identity from ordered components, parameters, data, split,
  clock, cost, engine, and source semantics.
- Freeze an adaptive Batch bound, acceptance profile, compute and wall limits,
  stop rule, expected artifacts, and evidence modes.
- For prospective scientific work use the active adjudication v2 validator.
  Preregister criterion roles as validity, component, multiplicity,
  risk_diagnostic, or risk_gate and preserve supported, contradicted,
  unresolved, invalid, and diagnostic states. Discovery maps a frontier and
  is always candidate-ineligible; only confirmation may request promotion-grade
  authority after every decisive gate passes.
- Treat `commitment_batches` as a positive finite upper bound, not blanket
  approval and not a project-wide tiny cap. The first frozen Batch uses the
  direct path. After an intermediate Batch, either close the Study early or
  record one typed `StudyContinuationDecision` before more work.
- Re-derive the exact registered member, one-Job-per-member completion set,
  durable output hashes, and stop-rule state from Writer records. Bind the
  unchanged Study question, chassis, axis, and current Portfolio. Review both
  close and continue using at least two material lenses, including every live
  alternative axis opportunity cost. A continue decision pre-binds one exact
  next Batch identity; a reached stop decision, absent evidence, drifted
  snapshot, different Batch, or commitment excess cannot continue.
- Count each unique Executable. Reuse identical success and reject unchanged
  failed retry.
- Keep Job input hashes sorted and unique. Repeating an existing input is not
  changed information and cannot create a new Job, retry, or cache identity.
- Resolve typed research evidence roles through the common verified-input
  snapshot. Separate those content-addressed evidence identities from other
  semantic Job hashes, read every declared evidence identity exactly once,
  require unique identities and exactly one artifact per requested schema, and
  bind a surface manifest to the exact surface artifact hash and the current
  Job output's expected implementation digest. This implementation check is
  not exact prior-Job producer authority. If future research reuses a prior Job
  output, require a typed exact-producer route then; do not prebuild an unused
  provenance framework now. Missing or hash-invalid evidence fails closed;
  only already verified noncanonical or unrelated artifacts may be skipped.
  Never verify and then reopen bytes through the EvidenceStore private root.
- Run research engines through the existing-lock, Journal-authenticated,
  query-only local-index capability. Workflow planning projections also use
  query-only SQLite and retain their stable-head guard. Missing or legacy
  projection state is a Writer recovery boundary, never permission for a
  reader to create or migrate SQLite state.
- Keep every worker ID, input, resource, and work-shard output claim portable
  and case-fold unique across the Job. Output claims divide internal work and
  are not a second spelling of the declared output-file contract.
- Use normalized relative ASCII POSIX Job output names with case-fold-unique
  spelling. Durable evidence stays below `evidence/`, `scientific/`, or
  `source/`; reproducible cache stays below `local/cache/`; transient output
  and logs stay below `local/jobs/`. Never use a physical or alias path to
  evade the declared storage class.
- Give every production Job, regardless of Mission, Initiative, Study,
  Executable, or Release subject, one exact recursive current source closure.
  Historical completion evidence is not an execution exemption, and embedded
  historical control IDs cannot be prospectively registered.
- When authoring a validator, declare every dependency that can change its
  scientific meaning or verdict as semantic identity input. Infer the remaining
  recursive execution closure separately and bind it to registry integrity and
  production Job implementation identity. Never expand semantic identity with
  unrelated framework imports or use closure-only classification to hide
  semantic drift. Genuine closure-only drift blocks or reidentifies future Job
  execution without renaming completed scientific claims, trials, or history.
- For an Executable whose implementation closure reaches
  `axiom_rift/research/external_observed_development.py`, derive the required
  external material and prefix hashes with
  `external_observed_development_job_input_hashes`, or use the caller-side
  `build_external_observed_development_job_spec` merger, before declaration.
  The Writer validates and never silently adds omitted inputs. The Executable
  manifest and source closure must agree in both directions on the exact
  current loader, material, prefix, and source set.
- At Job declaration, start, and cached-success reuse, verify only the exact
  materialized external prefix identity. Do not open the quarantined raw parent;
  do not repeat numeric parsing before the execution loader needs the frame.
- When one vectorized or cached engine evaluates a concurrent family, register
  every exact family Executable before the first member computation starts.
  A crash prefix must never contain evaluated family members that were absent
  from durable trial and exposure accounting.
- Treat `reproducible_cache` as evictable local acceleration, never scientific
  or terminal authority. A consumer may rematerialize missing bytes only from
  the exact durable producer completion and subject trace after canonical byte
  and hash verification. Existing mismatched bytes fail closed; cache absence
  alone never changes a Study or Mission disposition.
- Query semantic warnings; a caller-created equivalence object is not authority.
- A production Executable-bound implementation Repair cannot preserve an
  Executable merely by declaring unchanged semantics. Use the Writer-derived
  full semantic-equivalence plan and its dedicated registered validator. Only
  complete passed coverage of callable, protocol, evidence-binding, decision,
  lifecycle, cost, source, component, and claim surfaces permits in-place
  closure. The generic route additionally requires one exact source-closure
  manifest that explains the complete implementation artifact set, identical
  relative-path roles, exact per-changed-path measurements, and canonical AST
  equality of the opened `.py` bytes. A caller observation, raw hash-set match,
  closure JSON comparison, path swap, non-Python change, or changed AST is not
  generic equivalence. Use a protocol-specific validator for a stronger proven
  relation. A missing, partial, failed, not-evaluable, or unavailable
  equivalence result is a zero-credit Repair observation: keep Repair active
  and do not infer scientific change. Register a new Executable or Study scope
  through `requires_scientific_change` only after a separate registered
  validator positively proves that preserving the scientific identity is
  impossible.
- Treat comparison state and scientific state separately. A metric comparison
  may pass, fail, or be not_evaluable while its claim contribution is supported,
  contradicted, unresolved, invalid, or diagnostic. Use only scientific state
  for scheduler, negative-memory, exhaustion, or terminal reasoning.
- Close a Study only with an outcome compatible with the exact
  disposition-driving scientific completion. A legacy `not_evaluable` verdict
  cannot become `not_supported`; retain the rich v2 meaning that
  `partial_positive` is positive evidence even though its projected legacy
  verdict is `not_evaluable`. A prospective engineering or unavailable basis
  can close only as `evidence_gap` or `not_evaluable`, never as a scientific
  prune or falsification.
- An evidence-mode label, caller declaration, prior verdict, or cache artifact
  is not capability. The registered validator must recompute the exact protocol
  from durable subject-bound inputs and open the validation plan, atomic
  support, statistical proof, execution trace, and result manifest. Preserve
  protocol, data, split, Executable, decision, entry, exit, fold, regime,
  intent, gross PnL, native and stress cost, net PnL, and result attribution.
  Audit-integrity work has only `audit_integrity` effective scope and receives
  no scientific, economic, candidate, exhaustion, or terminal credit.

Prefer the smallest interpretable baseline contrast that can falsify the
question. Hold the common chassis fixed and change the declared primary layer.
Do not hide a multi-layer redesign inside a feature-named Study.
Use the reusable component, evaluation, selection-inference, and adjudication
engines for new work. Do not create another temporal Study runner when a
declarative plan over an existing primitive is sufficient. Historical runners
remain compatibility surfaces until exact parity evidence supports retirement.

## Data And Sources

Use completed bars and enforce feature and external availability at decision
time. Keep fit, calibration, development, restricted confirmation, quarantine,
and final forward evidence distinct. Require one-time HoldoutPermit for value
access; sealed ingestion exposes no values.

Derive a scheduled next-entry timestamp from the decision timestamp and frozen
clock contract, never by reading the next observed row. At execution, require
that the actual row equals that expected timestamp; a missing row fails closed
and cannot change the earlier session, selector, or routing decision.

Treat every inference-time external dependency as executable input. Offline
historical performance requires sealed content, valid semantics, an exact
SourcePermit, and a non-suspended source state; an expired wall-clock freshness
receipt alone does not invalidate immutable historical bytes. Runtime entry and
candidate-bound runtime evidence additionally require current synchronization,
freshness, closure, latency, and mapping checks. Fail stale, missing, late,
nonfinite, unsynchronized, or invalid mappings closed for the dependent sleeve
without stopping independent sleeves.

Treat `MqlRates.spread` as a completed-period observation, never as a point-in-
time quote at that bar's open or at a scheduled order. A decision may use the
completed decision bar and strictly earlier completed bars, but the scheduled
or deferred entry bar cannot provide spread, quote quality, cost-known,
abstention, cancellation, or further-deferral input to the order that enters on
it. A delayed-entry policy remains frozen at its declared decision time unless
a new causally available decision and new Executable semantics explicitly
replace it. Bind every historical entry and exit proxy to its exact completed-
bar source index and availability time; actual-quote claims require timestamped
bid-ask, tick, order, deal, or execution evidence.

A historical completed-bar cost qualification is an exact proxy-only scope.
Preserve independently supported gross mechanism or feature evidence, but make
actual/native-cost claims unresolved when point-in-time evidence is absent.
Proxy-dependent negative memory becomes diagnostic only and cannot prune,
exhaust, terminate, economically validate, or candidate-qualify an axis. An
affected historical prune projects as `deferred_requires_reopen` and needs the
typed additive reopen route before it is scheduled as preserved.

Current broker history is reconstruction, not proof of historical first
availability or vintage. If official MT5 time documentation and the observed
provider epoch coordinate disagree, preserve both facts and leave absolute
timezone, broker-session, and DST authority unknown; never infer a silent shift.
An audit-invalidated source head is latched. Ordinary same-semantics
recertification cannot restore it; follow its exact resolution policy, normally
a new source contract. Qualify every historical scientific result whose trial
binds that source as not evaluable through an additive provenance-bound overlay.
Keep the original Portfolio snapshot immutable. Read scheduling, architecture,
and terminal state through the current effective-axis projection, which applies
source invalidations, replay obligations, and evidence-scope overlays. Do not
schedule or credit an invalidated source axis until its typed resolution.

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

Project every disposition-driving completion through its current effective
evidence scope before diagnosis. Audit-only and scientific-validity-invalidated
completions retain their exact diagnostic claim inventory but cannot create
axis-level scientific confirmation debt. When no disposition-driving completion
retains scientific authority, use the typed non-identifiable branch rather than
promoting supported audit claims or a stale historical verdict.

If later scope authority changes a diagnosis that already has an additive
correction, bind the exact current correction and its audit and append the next
correction in that stream. Never reject later valid evidence merely because one
correction exists, and never overwrite or reinterpret either predecessor.

Classify engineering reentry from exact gap and repair evidence, not from a
diagnosis label alone. `not_identifiable` may support reentry only when the
bound record proves a recoverable non-scientific inability and the successor
produces its own valid result. A successor never inherits or rewrites prior
evidence; semantic revision remains a distinct estimand and cannot resolve the
predecessor question.

Interpret the validator independently of Job status. An operationally
successful Job may carry a failed scientific verdict, while an engineering or
source failure carries no scientific verdict. Use component-aware evidence to
preserve partial positives and exact contradicted claims instead of collapsing
the whole Executable into one universal negative.

When an audit creates a replay duty, operate its typed P0 or P1
ReplayObligation through pending, in_progress, satisfied, or deferred state.
Bind the exact original Study, adjudication, Executable, criteria, and evidence
  scope. Match each prospective Executable to at most one exact original
  Executable; never use first-trial, position, display order, or family-level
  fallback. Satisfy only after the registered validator recomputes the original
  subject-bound criteria. Otherwise retain the unresolved duty or record a typed
  defer condition and exact resume condition. P0 blocks the affected credit. P1
  gets the highest-information-value bounded opportunity without freezing
  unrelated valid forest work.

When one exact concurrent family covers more than one pending replay subject,
select the bounded obligation subset once and bind a canonical member assignment:
each selected obligation maps to one original Executable, one prospective
Executable, its exact criteria, and one target-specific historical-family
authority. Keep every preregistered control in Batch multiplicity, but attach no
obligation lineage to an unselected control. Never run the same complete family
once per member.

Register missing target-specific authorities for the selected pending members
once, through the bounded Writer registration event. Treat that event only as
historical admission: it changes no scheduler action and grants no science,
trial, claim, satisfaction, candidate, or holdout credit.

If a prior closed replay Study already executed and validly adjudicated omitted
siblings, use only the Writer-derived sibling-evidence recertification route.
It must reauthenticate the current source satisfaction and exact Decision,
Study, Batch, member trial, successful completion, close, diagnosis, criteria,
multiplicity, and frozen family authority. The source and target authorities
must share the exact immutable family core and reconstruction source bytes. It
adds no trial or candidate and accepts no caller-built satisfaction. On a later
engineering failure, atomically satisfy valid completed selected members and
defer only unresolved selected members.

Before any replay trial or Job consumes authority, require the exact Writer
admission defined by `contracts/operations.yaml` under
`replay_implementation_admission`. Route a legacy registration-only prefix
through its exact protocol rebind and recertification boundary; do not turn a
protocol migration or same-identity repair into scientific or replacement
failure, and never refund or recount its existing multiplicity.

Project an already canonical satisfied replay from its recorded stream,
same-event writer operation, immutable lineage, and evidence identities. Routine
Portfolio and effective-axis reads must not rerun the current scientific or
multiplicity protocol. Use current rules only through the writer's explicit
read-only satisfaction-invalidation plan.

If that audit proves an E01 family-size mismatch, cross-member family
disagreement, or a self-consistent registration whose member set differs from
its frozen Batch set, route the canonical plan and artifact. Bind the exact
registered membership and family hash. The same member set in a different
historical order is a noncredit audit diagnostic and cannot return the
obligation to pending; new prospective resolution still requires exact
canonical Batch-family order. Only the typed set, size, or family disagreement,
or the Writer-verified exact `evidence_completion_validity_invalid` defect
permitted by the current typed plan, may revoke satisfaction. The completion-
validity route cannot revoke an audit-only satisfaction. Malformed, missing,
hash-forged, or unrelated registration, caller prose, a generic validator
error, and unrelated evidence defects fail closed.

An audit-only satisfaction removes scientific, economic, candidate, exhaustion,
and terminal credit only from its exact completion. It never excludes the whole
causal axis. Keep open or preserved axes selectable; expose a historical prune
whose corrected completion may have mattered as `deferred_requires_reopen`, so
the Portfolio must explicitly preserve, reopen, or re-establish a valid prune.
When an exact preserve Decision targets that historical pruned state, consume
`record_axis_reopen_authority` before writing the preserved snapshot. The
v2 authority must bind the current snapshot, Decision, and axis plus exactly
one mutually exclusive typed route: the replay route binds the exact audit-only
replay resolution and evidence-scope overlay IDs; the historical-cost route
binds the exact completion, cost-semantics latch, and negative-memory IDs.
Never mix the route fields or use this authority for an ordinary prune.

The writer derives allowed local actions and research-layer branches from the
typed evidence state. The next Decision must either follow that branch,
dispose the diagnosed axis consistently, or make a genuinely structural forest
exit to a different layer or architecture. Adjacent same-chassis tuning is not
a structural exit.

A `supported_requires_confirmation` diagnosis keeps confirmation debt on its
exact axis; it does not grant that recent positive a global scheduler monopoly.
An unrelated `new_mechanism` exit is valid only when the Decision binds the
exact proposed axis before mutation and that axis differs from the diagnosed
source in primary layer or canonical architecture. The written Portfolio
snapshot must materialize that one proposal exactly. This exit gives no
confirmation credit to either axis.

## Architecture Review

When preregistered repeated gaps or negatives accumulate across enough Studies
and distinct axes under one architecture family, the writer emits
`review_architecture`. No Initiative close, Portfolio Decision, Study, Batch,
or Job may bypass it.

Bind `ArchitectureReview` to the exact `trigger_record_id`; this keeps repeated
reviews of one architecture distinct and binds each conclusion to its covered
diagnosis set.

Choose one typed conclusion:

- `bounded_same_architecture`: use only when the quant team identifies a
  bounded, testable continuation that the two exclusion conclusions would
  wrongly suppress. Bind the exact reviewed family, trigger, covered
  diagnoses, and stop/reopen condition. Select exactly one mode:
  - `existing_axis`: name one exact currently selectable axis ID and immutable
    axis identity under the reviewed family. Prior inclusion in the covered
    diagnosis set is not itself a veto.
  - `new_mechanism`: name one expert-selected typed `ResearchLayer`; the next
    Decision must be `new_mechanism`, and the added axis must use that layer
    and the exact reviewed family. Reuse the Portfolio's existing genuinely
    distinct mechanism-family rule.
- `change_research_layer`: require the next selected or newly admitted axis to
  leave the reviewed layers.
- `rotate_architecture`: require the next selected or newly admitted axis to
  leave the reviewed architecture family.

For `bounded_same_architecture`, use `ArchitectureReview` v2 with a typed
`ArchitectureContinuationDirection`. The Writer recomputes the trigger,
covered diagnoses, family, current snapshot, axis identity and selectability,
then projects a closed `required_architecture_family` constraint. The next
`QuantTeamDecisionReview` must cite the current Portfolio snapshot, the review,
its trigger, and every covered diagnosis. Free-form exceptions and caller
overrides are not capabilities.

The review is a scheduler and identifiability decision, not negative evidence.
It consumes only its exact unreviewed diagnosis set, so later genuinely new
evidence can trigger another bounded review.

## Disposition And Terminal Scope

Interpret causality, density, cost, economics, risk, stability, concentration,
and completeness non-compensatorily. Material Decisions retain at least one
structurally diversifying option and record omission reasons. Record preserve,
prune, deepen, rotate, contrast, new mechanism, complementary sleeve,
recombine, or synthesize with exact evidence scope and next action.

Call a result an economic composite only when the engine executes the actual
member trade rows with declared entry and exit timing, exposure netting, native
and stressed costs, and portfolio drawdown attribution. A component-summary
bundle, combined significance result, or composite label is not economic
evidence.

Do not mutate a Portfolio while a Study or Batch is active. Axis meaning is
immutable inside a Mission. A `closed_no_candidate` proposal requires every
axis to have an evidence-bound prune, preservation, replay, low-information
disposition, or reopen rule; it does not require falsely pruning unresolved or
invalid work. Bind the exact negative lineage, current evidence-bound exhaustion
standard, mechanism, research-layer, architecture, Study, Executable, and
validator-demonstrated depth, with no unresolved candidate-eligible positive
evidence.

## Mandatory Study KPI And User Report

Pass `StateWriter.close_study` only the final disposition-driving validator
`stop_batch` completion when one exists. Otherwise pass no completion and let
the writer derive the typed unavailable basis. For a started Batch, that
no-completion path is limited to exact frozen-budget exhaustion; engineering,
not-evaluable, and early-stop exits require a disposition-driving `stop_batch`
completion. Never turn `continue_batch` into close authority, and never pass
caller-authored KPI, unavailable prose, or a retrospective best result.

The writer creates one immutable `study-kpi` Journal record at close. The
lag-tolerant `records/STUDY_KPI.md` navigation view is reconstructed only during
explicit maintenance and may not delay later valid science. When materialized,
missing, invalid, censored, or inapplicable values render as `-`, never zero or
pass. Use the authenticated query projection for current research decisions.

At each Study close, explain in Korean chat:

- the causal hypothesis and primary research layer;
- the architecture family and what stayed controlled;
- the typed outcome and evidence-state interpretation;
- net profit, profit factor, trades, and drawdown share, preserving `-`;
- the exact follow-up or stop/reopen condition.

Return to `$operate-axiom-mission` for the required Study-close commit and push
before diagnosis or later scientific work.
