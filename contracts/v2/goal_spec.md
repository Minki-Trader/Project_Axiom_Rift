/goal

Build, prove, and activate Project Axiom Rift V2 in the current repository.

MISSION

Preserve the core philosophy and target of Axiom Rift:

- FPMarkets US100 M5.
- Approximately 5 to 10 total system entry events per eligible market day.
- Controlled monthly drawdown.
- Strong profitability after native spread and realistic slippage.
- Zero synthetic commission unless verified broker conditions change.
- Fixed-lot early research.
- Equity-percent sizing only after signal quality and robustness are established.
- Unrestricted exploration of labels, features, information sources, models,
  objectives, ensembles, entries, exits, and trade shapes until an
  evidence-based freeze.
- Failures preserved as useful assets.
- Claims never stronger than evidence.
- Native EA, ONNX model bundle, and reproducible pre-live handoff as the terminal
  project outcome.
- Live trading, capital deployment, VPS operation, and live authority remain
  outside this project.

Operate with principal-level multidisciplinary judgment equivalent to an
experienced quantitative trader, systematic researcher, macroeconomic and
market-regime specialist, data analyst, ML engineer, software architect, MQL5
developer, validation engineer, and pre-live trading-system operator.

User omissions are not exclusions. Proactively examine causality, market
microstructure, macro regimes, data quality, multiple testing, execution,
portfolio interaction, software design, Codex operation, reproducibility,
runtime portability, ONNX, EA behavior, and validation economics.

Prefer a materially better professional method over preserving a V1 method.
Do not over-engineer speculative abstractions. Build the smallest coherent
system that supports trustworthy end-to-end vertical operation.

V1 LEGACY BOUNDARY

Treat the entire V1 implementation and research history as legacy reference for
building V2, not as V2 active truth or V2 starting research state.

Do not continue C0144 or inherit:

- V1 campaign or run numbering.
- V1 hypotheses or research priorities.
- V1 candidate queues or preferred candidate lineages.
- V1 positive or negative alpha conclusions.
- V1 material-exhaustion conclusions.
- V1 labels, features, models, objectives, selectors, exits, or trade rules.
- V1 campaign granularity or copied run-module architecture.
- V1 validator sequence or nine-fold placement.
- V1 selected, economics, promotion, ONNX, runtime, or readiness status.

V1 may be used only for:

- Causality, leakage, parity, execution, and validation lessons.
- Software and operational failure lessons.
- Validation-time and execution-cost benchmarks.
- Identifying reusable data, MT5 runners, parsers, compilers, and infrastructure.
- Avoiding known architectural and experimental mistakes.

Every reused V1 component requires an explicit reuse, adapt, wrap, or replace
decision, a deficiency assessment, a parity boundary, a rollback boundary, and
a new V2 content identity. Reusing infrastructure must not inherit its research
conclusions.

Preserve V1 artifacts without treating them as claim authority. Do not repair or
rerun all historical campaigns. Classify legacy debt by affected scope.
Unrelated legacy hash or lineage debt may not block V2 construction, but it must
block any future claim that depends on the affected artifact.

Create fresh V2 contracts, registries, work-unit identities, hypothesis ledger,
negative memory, claim state, and evidence state. V2 material exhaustion must be
established only from V2 evidence.

If V2 independently rediscovers a V1-like idea, evaluate it as a new V2
hypothesis. Do not transfer V1 performance, failure, selection, or exhaustion
status into it.

CURRENT GOAL SCOPE

This goal builds and activates the V2 operating system. It must not expand into
an unbounded search for a profitable production candidate.

Do not stop at planning, documentation, schemas, scaffolding, imports, or
compilation. Implement the operating system, prove its critical paths, activate
it as the unambiguous project truth, and prepare the exact next V2 research
action.

Use a same-repository strangler transition by default:

- Keep V1 legacy surfaces stable.
- Build a clean V2 control plane and modular V2 core.
- Migrate only justified reusable components.
- Preserve evidence identity and unrelated user work.
- Replace one boundary at a time.
- Retire legacy components only after replacement parity and consumer migration.
- Do not rewrite the historical project wholesale.
- Do not maintain two mutable active truths after V2 activation.

V2 GOVERNANCE

Build and activate:

- A thin AGENTS.md router.
- Concise V2 project, evaluation, claim, data, research, materialization,
  validation, and handoff contracts.
- A minimal focused V2 skill set.
- A compact decision cursor and reentry state.
- A transactional claim-state mechanism.
- A content-addressed hypothesis and evidence ledger.
- A feature, label, model, selector, and trade-program material ledger.
- A validation-receipt registry.
- A data, calendar, split, and holdout identity registry.
- A future one-goal end-to-end campaign operator.
- Explicit V1-to-V2 activation and rollback boundaries.

Keep active project files machine-oriented, concise, canonical, and ASCII-only.
Keep Korean explanation in chat.

Do not duplicate detailed policy across AGENTS.md, contracts, skills, and
validators. Put each rule in its smallest authoritative surface.

V2 RESEARCH RESET

Begin V2 with a blank hypothesis state and a new V2 work-unit namespace.

Before consulting V1 alpha results, construct and preregister a broad V2 research
map covering meaningful axes such as:

- Causal market state and microstructure.
- Labels, horizons, path outcomes, and time-to-event objectives.
- Model families and learning objectives.
- Sequential selection and abstention.
- Entry and order types.
- Exit and position-lifecycle models.
- Direction-specific behavior.
- Regime mixtures and portfolio sleeves.
- Volatility, liquidity, session, and calendar structure.
- Macroeconomic event risk.
- Runtime-audited cross-asset context.
- Execution-aware and cost-aware objectives.

Do not force every axis into the first batch. Rank axes by expected information
gain, causal feasibility, data availability, execution portability, portfolio
value, and research cost.

After preregistration, V1 may be checked only for mechanical duplication,
noncausal logic, known implementation hazards, or reusable plumbing. V1
performance rankings must not select the initial V2 hypotheses.

Measure novelty from executable identity rather than prose. Track:

- Feature formula DAG hash.
- Label-program hash.
- Model and objective hash.
- Selector hash.
- Entry and exit rule hash.
- Data-source identity.
- Event and schedule overlap.
- Daily PnL correlation.
- Expected decision payoff.
- ONNX and EA portability.

Renaming a formula or changing a narrative is not a new research axis. Reject
low-information adjacent tuning before expensive execution.

CAUSAL DATA AND MARKET-TIME FOUNDATION

Implement an explicit point-in-time contract containing:

- Broker server bar-open time.
- Bar-close time.
- Decision availability time.
- UTC time.
- America/New_York market time.
- Broker timezone and DST version.
- Exchange calendar version.
- Gap, closure, and blackout policy.

Treat MqlRates.time as bar-open time. A closed M5 bar may not be used before its
close and decision availability time.

Require:

- feature_available_at <= decision_time
- external_available_at <= decision_time
- feature prefix invariance
- completed-decision append invariance
- fold-isolated fitting
- sequential OOS decisions
- explicit missing and stale input behavior

Forbid:

- Same-day future candidate ranking.
- Full-day top-K entry selection.
- Future candidate-count dependence.
- Test or holdout outcomes influencing calibration.
- Silent external-data forward filling.
- Historically revised macro data being treated as originally available data.

Use calibrated sequential admission with abstention. A maximum daily-entry value
may be a safety cap but never a quota.

Measure entry frequency across all eligible market days and include:

- Entries per eligible market day.
- Zero-entry-day rate.
- Daily entry-count p10, median, and p90.
- Maximum daily entries.
- Direction, session, regime, and exposure concentration.

Evaluate the 5-to-10 entry target at the total portfolio level after sleeve
combination and exposure netting. Do not force each alpha to meet it alone.

DATA, SPLIT, AND MULTIPLE-TESTING POLICY

Every reusable dataset must have a hash-keyed receipt containing source identity,
processed identity, schema, row count, time boundaries, calendar, timezone, gap
mask, blackout mask, split identity, and symbol specification.

Run complete data validation once per unchanged dataset identity and reuse the
receipt.

Give splits distinct roles:

- train_is: preprocessing and model fitting
- validation_oos: calibration, threshold selection, hyperparameter choice, and
  early rejection
- development_cv: repeated adaptive research comparison
- limited_test_oos: restricted family confirmation
- forward_holdout: locked one-time final confirmation

Treat the existing repeatedly observed nine folds as development CV, not final
OOS. Separate evaluated folds from reserved holdouts.

Freeze candidate code, data, feature order, preprocessing, model, selector, and
trade rules before revealing a forward holdout. Do not tune on the same holdout
after reveal. A failed final holdout requires new future data.

Track total trials, family trials, candidate selections, and holdout reveals.
Use bootstrap stability, selection-adjusted confidence, PBO, SPA, or a justified
equivalent when adaptive search materially affects a claim.

FUTURE ONE-GOAL RESEARCH LIFECYCLE

Build the future operator so one /goal owns one complete logical research
operation. Compaction and continuation turns remain the same logical session.
Moving to the next stage must not require another user goal.

Use these internal stages:

H - Hypothesis batch
- Define a small preregistered batch.
- Record the question, executable identities, split roles, falsification rules,
  acceptance profile, novelty, portability, expected information gain, evidence
  budget, and claim ceiling.
- Reject duplicates and known noncausal designs before execution.

S - Causal scout
- Use cached vectorized computation and a small predeclared representative
  development subset.
- Test causality, leakage, event density, activity distribution, basic
  after-cost economics, direction and regime sanity, and portability.
- No MT5 requirement and no candidate, execution, or economics claim.
- A weak scout may terminate honestly without promotion-grade validation.

R - Confirmation
- Open an evidence-bearing run only after scout survival.
- Use the required development folds with fold-isolated fitting, causal
  sequential selection, uncertainty reporting, and trial accounting.
- Use minimal certified MT5 confirmation.
- If the engine, schedule schema, exit semantics, symbol contract, and tester
  model retain a valid conformance receipt, default to one aggregate closed-bar
  logic run and one aggregate real-tick run.
- Partition aggregate ledgers by fold only after boundary equivalence is proven.
- End with either confirmed negative evidence or research-candidate evidence.

P - Promotion
- Apply expensive validation only to a small number of genuine candidates.
- Require isolated nine-fold MT5 when promoting, recertifying a changed engine,
  or when aggregate partition equivalence is invalid.
- Include realistic spread and slippage stress, monthly drawdown, expectancy,
  turnover, exposure, time under water, direction/session/regime breakdown,
  multiple-testing adjustment, portfolio contribution, and locked holdout or
  forward confirmation.

M - Materialization
- When a candidate survives promotion, continue in the same goal.
- Freeze all relevant identities.
- Refit only on the permitted final training boundary.
- Produce the model artifact and ONNX artifact.
- Integrate an actual online signal-generating EA.
- Complete Python, ONNX, MQL5, decision, lifecycle, and MT5 parity.
- Produce the reproducible pre-live handoff.

The honest terminal outcomes of a future research goal are:

- completed_pre_live_handoff
- closed_no_candidate
- blocked_external
- stopped_by_user

If no hypothesis survives, close with useful V2 negative memory and do not
produce meaningless ONNX or EA artifacts.

If a candidate survives, do not stop at research results, Python code, proxy
results, ONNX export, EA compilation, or schedule replay. Continue in the same
goal until pre-live evidence is complete or a genuine external blocker exists.

SOFTWARE ARCHITECTURE

Build a modular system with explicit boundaries for:

- Data and market clock.
- Causal features.
- Labels and objectives.
- Models and calibration.
- Sequential admission.
- Trade and position simulation.
- Cost and execution modeling.
- Evidence and state transactions.
- MT5 running and parsing.
- ONNX materialization.
- EA runtime integration.
- Validation receipts.

Use declarative hypothesis specifications and a generic runner. Hypothesis code
must define only its true research variation. It must not directly rewrite
claim state, registries, KPI schemas, or generic execution plumbing.

Forbid:

- Full copies of earlier run modules.
- Duplicate top-level definitions.
- Campaign-specific paths inside core modules.
- Core modules importing historical campaign code.
- Hand-maintained duplicate feature-order lists.
- Run-specific direct registry mutation.
- Shared modules being rewritten from memory when a reusable source exists.

Create one canonical feature specification shared by Python, ONNX, and MQL5.
It must define names, order, dtype, shape, normalization, warmup,
missing-value behavior, availability semantics, and a feature-order hash.

Keep EA bodies thin and move reusable MQL logic into MQH modules. Keep training,
parsing, hashing, ledgers, and evidence generation in Python.

ONNX AND NATIVE EA EVIDENCE

The preferred ONNX boundary is a fixed float32 feature vector to model score.
Keep canonical clock, causal rolling state, missing or stale input state,
sequential admission, positions, and execution outside ONNX unless another
boundary is explicitly justified.

Require parity in this order:

1. Raw input fixture parity.
2. Python feature versus MQL feature parity.
3. Python model versus ONNX Runtime score parity.
4. ONNX Runtime versus EA ONNX score parity.
5. Python decision versus native EA decision parity.
6. Entry, exit, and position-lifecycle parity.
7. Native EA closed-bar logic parity.
8. Native EA real-tick execution economics.

Timestamps and directions require exact parity. Numeric tolerances must be
declared before evaluation.

Schedule replay may prove schedule I/O, execution handling, and position
management. It cannot prove causal feature generation, native signal generation,
ONNX inference, or ONNX readiness.

Materialization must test:

- Cold start and warmup.
- Duplicate-bar protection.
- Restart and state recovery.
- Missing and stale inputs.
- Model-load failure.
- Clock and DST behavior.
- Broker symbol specification.
- Feature-order hash enforcement.
- Missing KPI detection.

VALIDATION ECONOMICS

Prime rule:

Never spend promotion-grade validation on scout-grade evidence, and never create
promotion-grade claims from scout-grade validation.

A validator is a fast receipt checker. It must not launch data builds, training,
MT5 testing, ONNX export, downloads, or another long evidence job.

Routine validators must:

- Target 3 to 15 seconds.
- Use a default hard ceiling of 30 seconds.
- Validate changed surfaces only.
- Fail fast on missing prerequisites.
- Reuse successful receipts with identical validator, input, and config hashes.
- Never rerun an unchanged successful receipt.

Anything expected to exceed 30 seconds is an explicit evidence job, not a
validator. Long evidence jobs must be declared, bounded, hash-keyed, logged,
resumable, and run without preventing safe independent work.

For each coherent implementation slice use:

1. One slice specification.
2. One batched implementation.
3. One focused validation batch.
4. At most one consolidated repair batch.
5. One focused recheck.

Do not validate after every file edit. Do not fix one error and repeatedly rerun
a broad validator. Do not automatically retry identical failures or extend
timeouts.

A repeated failure requires root-cause review and boundary redesign, component
replacement, or a complete blocker record.

Cache unchanged data checks, feature matrices, compiled artifacts, engine
conformance, fold schedules, and successful validation receipts.

Compile once, generate schedules once, execute an evidence batch once, parse it
once, update state once, and commit once. Do not mutate registries or create
commits independently for every fold.

Reserve complete repository validation for V2 activation, shared-core changes,
promotion, materialization freeze, pre-live handoff, and explicit integrity
audits.

Broken code is never hypothesis evidence. Repair in-scope failures and rerun the
same focused check. A valid blocker requires root cause, reproduction command,
failing artifact, affected claims, completed safe work, exact resume action,
and required external state.

CLAIM LADDER

Implement an ordered claim ladder:

- diagnostic_observation
- research_candidate
- robustness_candidate
- economics_pass
- selected
- onnx_ready
- materialization_ready
- pre_live_ready

No claim may skip required evidence.

An ONNX file alone is not onnx_ready.
EA compilation alone is not materialization_ready.
Schedule replay is not native runtime authority.
Aggregate profit is not robustness evidence.
Development CV is not final OOS.
A pre-live package is not live_ready.
No live_ready claim may be created inside Axiom Rift.

CODEX OPERATING MODEL

Use GPT-5.6 with high reasoning as the main V2 construction setting. Use higher
reasoning only for a bounded architecture or final integration decision when it
has clear value. Do not compensate for slow or broken evidence jobs by
increasing reasoning effort.

Before mutation, create a compact goal packet containing:

- Goal ID and objective.
- Claim ceiling.
- Acceptance profile.
- Architecture and reuse decisions.
- Allowed paths.
- Evidence plan.
- Validator and repair budgets.
- Git base and head.
- Terminal conditions.

Freeze acceptance rules before viewing results.

Maintain one active coherent implementation slice and one exact next action.
Use parallel agents only for independent read-only investigation or clearly
non-overlapping implementation. The root operator owns integration, claims,
overlapping edits, and final decisions.

Update compact reentry state at phase gates, before and after long jobs, before
compaction, at blockers, and at closeout. Record completed receipt IDs, artifact
hashes, active job state, remaining budgets, exact next action, and git head.
Do not use a giant narrative history as active state.

Continue autonomously without asking for routine implementation decisions.
Request user direction only for a material scope change, destructive or
irreversible action, new external authority, capital or live operation, or a
genuine external blocker.

GIT POLICY

Preserve unrelated user work.

Do not force-push, hard reset, discard unrelated changes, or stage unrelated
files.

Use milestone commits for coherent governance, core, research-engine,
materialization, and activation batches. Do not commit every micro-fix.

Actual evidence-bearing run closeouts and final V2 activation must be reflected
on local main and pushed to origin/main after relevant validation. If git sync
cannot complete, record a complete blocker and do not report operational
completion.

V2 CONSTRUCTION DONE DEFINITION

This goal is complete only when:

- V1 is formally classified as legacy reference, not V2 research truth.
- V2 begins with a fresh research and claim state.
- One unambiguous V2 active governance path exists.
- V2 AGENTS routing, contracts, skills, registries, claim ladder, and reentry are
  active.
- Causal time, selector, data, activity, split, and holdout contracts are
  implemented.
- The modular V2 research runner exists without copied V1 campaign modules.
- Executable novelty and material ledgers exist.
- Validation receipts, caching, and the sub-30-second routine validator ceiling
  are implemented and measured.
- H, S, R, P, and M transitions are executable without separate user goals.
- Full isolated nine-fold MT5 is restricted to promotion or recertification
  conditions.
- One deterministic non-economic fixture proves the full technical path without
  creating an economics claim.
- One newly originated and preregistered V2 hypothesis completes a bounded
  real-data causal scout without inheriting a V1 candidate.
- Python, ONNX, MQL5, native EA, and MT5 parity paths are executable.
- A thin online signal-generating EA reference path exists.
- A future single research goal can progress to either closed_no_candidate or
  completed_pre_live_handoff.
- Existing legacy debt is separately classified.
- The exact first post-activation V2 research action is recorded.
- Goal-scoped changes pass the relevant activation checks.
- Reentry and claim state are honest.
- Changes are committed, reflected on main, and pushed to origin/main.

Do not report completion from a proposal, partial scaffold, compile-only result,
unfinished long job, missing receipt, uncommitted change, or unpushed closeout.

