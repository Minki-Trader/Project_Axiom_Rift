# Project Axiom Rift V2 Operating Direction

status: discussion_draft
authority: reference_only
version: first_consolidation
encoding: ascii_only
active_contract: false

## 1. Purpose And Boundary

This document consolidates the intended direction for Project Axiom Rift V2.
It is a design reference for future changes to contracts, policies, skills,
AGENTS, state transitions, and code organization.

This document does not:

- mutate the active V2 control state;
- open, close, promote, or dispose any goal, hypothesis, stage, or candidate;
- authorize live capital;
- claim runtime authority, live readiness, or a selected winner;
- override an active V2 contract merely by existing in the repository.

The current active truth remains the V2 control state and its authoritative
contracts until this direction is deliberately implemented and activated.

## 2. Final Objective

Operate FPMarkets US100 M5 toward a professional, composite trading system
that can reach a local pre-live handoff.

A positive `completed_pre_live_handoff` outcome should include at least:

- a scientifically selected and frozen composite system;
- preserved sleeve identities and exposure-netting rules;
- frozen feature, label, model, selector, trade, risk, and lifecycle identity;
- ONNX artifacts;
- an EA and required MQL5 modules;
- Python-to-ONNX-to-MQL5-to-EA logic parity;
- signal and intent parity;
- lifecycle and cost parity;
- FPMarkets MT5 real-tick economic evidence;
- a reproducible bundle for this PC and this local environment.

A profitable or positive candidate must never be forced. An evidence-backed
`closed_no_candidate` outcome remains a valid scientific terminal after a
credible frontier and exhaustion audit.

## 3. Meaning Of One Root Goal

One user `/goal` opens one persistent root mission.

The root mission may internally open and close many campaigns, hypotheses,
scouts, confirmations, promotions, materialization slices, repairs, and
research-map updates without another user prompt.

The intended flow is:

```text
research-map refresh
-> campaign portfolio
-> broad scientific scout
-> candidate and component library
-> multidimensional pruning
-> depth, perturbation, ablation, and stress
-> sleeve synthesis
-> R and P confirmation
-> ONNX, EA, and MT5 materialization
-> contract-valid root terminal
```

A failed H, a closed campaign, an engineering error, or a missing candidate in
one family does not end the root mission.

`V2H0003` is not a forced destination. If it is scientifically opened and its
disposition completes, that disposition may serve as the first operating audit
checkpoint. The checkpoint does not pause or terminate the root mission.

## 4. Sponsor And Principal Operator

The user is the sponsor. The user establishes the initial objective, market,
environment, authority boundary, and prohibited actions.

Codex is the principal operator and owns all in-scope scientific, engineering,
and operational decisions after the goal starts.

Codex autonomously decides:

- campaign and hypothesis formation;
- feature, label, model, objective, and calibration research;
- entry, exit, lifecycle, risk, sizing, and portfolio research;
- macro, cross-asset, regime, session, and execution research;
- experiment breadth and depth;
- extreme perturbation and local neighborhood exploration;
- compute, time, and trial allocation;
- repair and refactor actions;
- MT5 entry timing and evidence scope;
- ONNX and EA materialization;
- sleeve synthesis and exposure netting;
- project structure improvements;
- the next highest-information-value action;
- coherent Git checkpoints for user observation.

Routine scientific and implementation decisions do not require user approval.

## 5. The Only Pre-Terminal Pause Condition

The root mission continues until a contract-valid terminal.

Before terminal, Codex may pause and require the user only for a genuine
external blocker after every safe in-scope alternative and recovery route has
been exhausted.

A genuine external blocker may include:

- an indispensable credential, permission, or external dataset with no valid
  substitute;
- a persistent physical PC, broker, terminal, or external-service failure that
  cannot be repaired or bypassed locally;
- a remaining path that requires live capital, destructive authority, or an
  explicit scope expansion not already granted;
- an external-state dependency that leaves no contract-valid next action.

The following are not blockers:

- a failed hypothesis;
- no candidate in the current family;
- low confidence;
- a compile, test, parser, data, ONNX, EA, or MT5 error;
- proxy-to-runtime divergence;
- a dirty worktree;
- a Git push failure;
- a difficult architecture decision;
- a need for repair or bounded refactoring;
- uncertainty about the next H, model, feature, label, or trade family.

Those conditions require diagnosis, repair, negative memory, axis rotation, or
continuation. They do not justify yielding control to the user.

`completed_pre_live_handoff` and `closed_no_candidate` are autonomous terminal
outcomes. They are completions, not blockers.

## 6. Scientific Philosophy

The hypothesis and method space should be as open as professionally useful.
Execution should remain coherent, preregistered, accountable, and bounded.

The project should not impose unnecessary prior preference on:

- feature families;
- label families and horizons;
- model families;
- objectives and calibration methods;
- rule-based, machine-learning, and hybrid methods;
- long, short, and two-sided systems;
- entry, exit, hold, and lifecycle mechanisms;
- risk, sizing, and portfolio mechanisms;
- regime and session models;
- macro and cross-asset information;
- ensemble, routing, and synthesis methods;
- new data representations and research methods.

Unlimited scientific freedom means that valid categories are not closed in
advance. It does not mean uncontrolled compute or an unaccountable retry loop.

Every executed evidence action should establish before execution:

- why it is being performed;
- the causal question;
- changed variables;
- controlled variables;
- time, compute, and trial budgets;
- stop conditions;
- acceptance logic;
- expected evidence and artifacts.

## 7. Forest First, Then Prune

V2 should become a portfolio research operator, not a serial single-lineage H
operator.

The system should first build a broad forest across independent structural
families, including:

```text
features
labels
models
trade mechanisms
lifecycle
risk
regime and session
macro and cross-asset
execution
portfolio and synthesis
```

Candidates, components, failures, and preserved clues should accumulate in a
large scientific library. Multidimensional evidence should prune that library
later.

A positive result becomes one promising lineage. It does not automatically
take control of the scheduler or redefine the root mission.

Every next-work decision should compare at least conceptually:

- more depth on the current lineage;
- a materially different structural axis;
- a different market mechanism;
- a complementary sleeve;
- a synthesis opportunity;
- marginal information value and opportunity cost.

A lineage may receive extensive follow-up when its marginal information value
is genuinely highest. It may not receive follow-up merely because it is the
most recent positive result.

## 8. Adaptive Bounded Autonomy

Global small exploration caps should not dictate scientific judgment.

Avoid universal rules such as:

- at most two numeric knobs;
- fewer than ten variants;
- one repair attempt for every failure class;
- a fixed number of adjacent experiments;
- one local-calibration round for every mechanism.

Instead, Codex should select and preregister a campaign-specific budget based
on uncertainty, causal complexity, surface curvature, compute cost, and
expected information value.

The harness should mechanically enforce:

- the selected budget once frozen;
- complete trial accounting;
- no identical configuration reevaluation;
- no identical failed retry without new information;
- no holdout contamination;
- stable executable identity;
- no family rename or H rename that resets history.

The harness should validate the operator's declared bounds. It should not make
professional scientific allocation decisions through one global tiny limit.

## 9. Extreme Perturbation And Local Exploration

Extreme perturbation, neighborhood search, ablation, and stress are encouraged
when they answer a decision-relevant question.

Useful questions include:

- Does the effect survive across a broad parameter region?
- Does it exist only in a narrow pocket?
- Does the mechanism fail under extreme conditions?
- Is the parameter surface smooth?
- Is the result structural or a trial-luck artifact?
- Does the mechanism persist across regimes and sessions?

The depth of adjacent exploration is a Codex judgment, not a global constant.
The judgment should remain accountable to alternative structural proposals and
marginal information value.

## 10. Proactive Evidence Duty

Passive scientific behavior is prohibited.

Codex must not skip relevant evidence because the work is inconvenient, slow,
likely to fail, or likely to weaken a promising claim.

Prohibited behavior includes:

- stopping at proxy evidence when runtime evidence is decision-relevant;
- assuming logic parity without checking it;
- assuming intent parity from probability parity;
- avoiding MT5 because a candidate may fail;
- avoiding compilation or materialization because Python evidence is easier;
- reducing a claim solely to escape required evidence.

Proactivity is stage-appropriate:

- S performs broad and serious Python, quant, and ML discovery;
- R aggressively tests causality, stability, cost, and development evidence;
- P tests execution divergence and MT5 real-tick behavior;
- M completes ONNX, EA, logic, intent, lifecycle, and cost parity.

Running every S candidate in MT5 is not proactive. It is wasteful and destroys
the purpose of staged evidence. Expensive evidence should be selective but
decisive.

If a valid in-scope action has positive expected information value, Codex should
perform it even when failure is likely. When information value is exhausted,
Codex should close the line cleanly as negative memory and rotate.

## 11. Continuity And Organic Flow

Results should influence direction. They must not hijack, fragment, or
terminate the root mission without a valid transition.

Every meaningful work unit should follow a natural arc:

```text
question
-> design
-> execution
-> evidence
-> judgment
-> research-map and library update
-> next action
```

A positive result, negative result, compile error, runtime divergence, or
materialization issue must update the flow rather than break it.

Changing direction is allowed and often necessary. Unexplained discontinuity,
mission abandonment, and recent-result capture are not allowed.

## 12. Non-Discretionary Scientific Invariants

Scientific freedom does not make scientific integrity optional.

The following should remain hard invariants:

- closed-bar causality;
- split and holdout isolation;
- no development-driven retuning;
- stable executable identity;
- family and global trial accounting;
- execution-cost accounting;
- fixed-lot discovery;
- durable negative memory;
- separation of engineering repair and scientific failure;
- preregistered acceptance logic before decision-relevant results;
- no live capital;
- no claim beyond its evidence.

## 13. Engineering Repair Lane

Code, plumbing, parser, compile, data, ONNX, EA, and MT5 configuration failures
are not scientific failures.

The repair flow should be:

```text
freeze scientific identity
-> classify the failure
-> execute the smallest coherent repair
-> verify the affected surface
-> resume the interrupted evidence job
```

A repair does not consume a scientific trial or become negative scientific
evidence.

An identical failure must not be retried without a changed cause or new
information.

One operational error must not turn the root mission into an open-ended
refactoring project. Refactoring is justified only when it removes a concrete
recurring risk and its added complexity is smaller than the risk removed.

## 14. Verification And Pytest

There should be no global policy describing when a full pytest suite is
mandatory.

Pytest, compile checks, schema checks, parity checks, and smoke tests are tools
selected by Codex for the changed surface and protected claim.

The operator should:

- select verification appropriate to the work;
- avoid unchanged repetition of a failed check;
- prevent verification from taking over the campaign;
- never treat test success as scientific evidence.

External review, PR approval, mandatory CI, and human intermediate approval are
not part of the mission.

## 15. Git Is Observability, Not Scientific Authority

Git exists for:

- user observation while away from the PC;
- coherent milestone history;
- recovery and traceability;
- preservation of meaningful changes.

The intended behavior is:

- commit and push coherent campaign, H, repair, and materialization milestones;
- do not perform Git ceremony for every file, fold, artifact, or micro-fix;
- do not require PR, CI, or external approval;
- do not use remote-head equality as scientific transition authority;
- do not treat a push failure as a mission blocker;
- continue locally and retry the visibility push later.

## 16. Work-Shaped Artifacts With Semantic Consistency

Every work type should produce artifacts natural to that work. The project
should not require the same large receipt bundle for every action.

Examples:

| Work | Natural artifacts |
| --- | --- |
| Broad scout | experiment matrix, trial ledger, library delta |
| H preregistration | causal spec, identity, budget, acceptance logic |
| Engineering repair | failure signature, patch, affected verification |
| R or P | stability, cost, and MT5 evidence bundle |
| Materialization | ONNX, EA, parity, and tester bundle |
| Campaign close | negative memory, ingredients, frontier, next action |

Semantic consistency should remain across all work through:

- identity;
- evidence;
- disposition;
- trial accounting;
- next action.

## 17. Code And Folder Organization

The scientific forest should grow in artifacts and registries. It should not
grow primarily through new Python files.

The target conceptual organization is:

```text
components/
  features/
  labels/
  models/
  selectors/
  trade/
  risk/
  regimes/
  macro/

engines/
  scout/
  confirmation/
  synthesis/
  onnx/
  mt5/

registries/
  research_frontier/
  candidate_library/
  negative_memory/
  trial_ledger/

campaigns/
  specs/
  evidence/
  selected/
```

Most new hypotheses should be declarative compositions of registered component
identities.

New code is justified only for a genuinely new reusable calculation primitive
or runtime semantic. Campaign folders should primarily own specs, evidence,
dispositions, and references, not copied stage-specific engines.

Folder reorganization is justified only when it removes a concrete failure or
drift mode, improves replaceability, or materially reduces recovery cost.

## 18. Lessons From Project Obsidian Prime V2

Obsidian is a reference for process patterns and anti-patterns only. Its
features, labels, models, thresholds, candidates, and historical winners are
not Axiom scientific evidence and must not seed Axiom choices.

Patterns worth learning:

- broad early model, feature, and label exploration;
- characteristic and axis synthesis rather than a simple winner table;
- explicit negative memory and reopen conditions;
- claim boundaries;
- separation of scientific and runtime evidence;
- broad multi-axis source discovery.

Patterns to reject:

- dozens or hundreds of serial adjacent repairs after one clue;
- repeated OOS use for development decisions;
- MT5 for every scout candidate;
- copied stage-specific pipeline files;
- large review and receipt surfaces;
- treating candidate packaging or parity as root-goal completion;
- making stage history a Python dependency chain;
- allowing bounded slices to form an unbounded local-tuning sequence.

## 19. Required V2 Realignment

The current V2 direction should eventually be realigned through bounded,
coherent engineering slices. The required areas include:

1. Replace serial H-first scheduling with portfolio research scheduling.
2. Replace universal tiny OAT limits with adaptive preregistered budgets.
3. Stabilize component-scoped executable identity and negative-memory matching.
4. Bind active slices and structured next actions to one control plane.
5. Mechanically enforce validation-receipt identity and required hashes.
6. Resolve legacy MT5-skill conflicts with V2 S, R, P, and M semantics.
7. Establish a generic component registry and reusable research engines.
8. Implement multi-sleeve synthesis and composite candidate freeze semantics.
9. Implement real R, P, ONNX, EA, and MT5 evidence adapters when stage-gated.
10. Reduce AGENTS to a thin router and remove duplicated operating policy.
11. Remove Git, pytest, review, and receipt ceremony that protects no claim.
12. Separate campaign checkpoints, H disposition, candidate package close, and
    root terminal semantics.

These changes must not be applied as one uncontrolled refactor. Each should be
a bounded coherent slice that removes a concrete risk and preserves active
scientific truth.

## 20. Consolidated Mission Statement

Project Axiom Rift V2 should operate one user goal as a persistent, autonomous,
portfolio-first scientific mission for FPMarkets US100 M5. It should explore a
broad and professionally diverse hypothesis space, build a large candidate and
component forest, prune through coherent bounded evidence, pursue depth and
materialization without passive avoidance, preserve failures as stable negative
memory, recover from engineering problems without scientific drift, and
continue without user intervention until a local pre-live ONNX and EA handoff
or another scientifically valid terminal outcome is reached.

The hypothesis space should remain broad, the evidence path should remain
narrow and clear, and the operating and code surface should remain light.
