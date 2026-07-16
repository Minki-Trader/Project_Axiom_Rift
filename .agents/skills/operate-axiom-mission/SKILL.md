---
name: operate-axiom-mission
description: Operate the persistent Axiom Project Goal through one active first or successor Mission, including bare or one-line /goal intake, mandatory Mission research intake, audit correction, authority migration, replay routing, Study-close delivery, diagnosis and architecture-review routing, continuation, Decisions, Repairs, blockers, Mission terminals, reentry, closeout, and Git observation. Use for /goal, exact next-action routing, or any request that may change canonical control state.
---

# Operate Axiom Project Goal

Use the repository as authority. Do not depend on chat history.

## Boot

1. Read `AGENTS.md`.
2. Read `state/control.json`.
3. Read the active record named by control state. At a Mission-admission
   boundary, read its exact predecessor terminal instead.
4. Read only the contracts required by the classified action.
5. Audit every prospective real `study-kpi` record against Git.  Its exact
   `study_closed` event ID and revision must identify exactly one commit
   reachable from local `main` through the required trailers.  That commit
   must change all three required projection paths; its snapshot must end the
   Journal and control head at that exact event/revision, and its KPI file
   bytes must equal the deterministic render of all Journal `study-kpi`
   records in that snapshot.  If this authenticated commit is absent, resume the
   closeout delivery before any state or science action.  Refresh the
   `origin/main` observation, require the closeout commit to be its ancestor,
   and otherwise make the immediate non-force push attempt before new science
   while retaining same-commit delivery debt after a bounded failed attempt.
   Audit a `historical_backfill` provenance set as one authenticated
   `study_kpi_backfilled` checkpoint instead of requiring fictional commits at
   each old close time; its commit snapshot must bind the complete original
   close set and exact deterministic ledger bytes.
   A sponsor-authorized `study_close_delivery_repair` attestation may satisfy
   this audit only for an exact listed prospective commit that already changed
   all three required paths and whose tree, Journal tail, control head, and
   deterministic KPI bytes are correct. Require the original commit and the
   attestation checkpoint to be reachable from local `main` and ancestors of
   `origin/main`. The repair cannot replace missing or incorrect scientific or
   projection content and cannot create another Study-close snapshot.
   Require `git config --get core.hooksPath` to equal `.githooks`; run
   `scripts/install_git_hooks.py` when absent or different. At routine state
   boundaries let the Writer authenticate the tracked
   `records/STUDY_CLOSE_DELIVERY_CHECKPOINT.json`, seek its exact Journal
   boundary, and validate only the bounded Journal and local-main suffix. The
   ignored local cache is a hint and its deletion or contents never establish
   delivery. Initialize the tracked checkpoint only with
   `scripts/audit_all_study_close_deliveries.py --initialize-checkpoint`; its
   commit-msg validation repeats the complete audit. After initialization, a
   missing, modified, or malformed tracked checkpoint blocks later science and
   never falls back to the ignored cache or a routine complete-history scan.
   The active checkpoint schema is v2. Upgrade v1 only through the explicit
   full-maintenance path, which authenticates the exact twenty-one-row
   historical backfill source set and binds each source close, commit, tree,
   path blob, trailer or typed attestation, ancestry, and deterministic KPI
   bytes. Routine operation uses the fast bounded suffix guard; a complete
   reconstruction or exact-staging audit runs only when explicitly required.
   Close and no-close boundaries are monotone and a no-close boundary cannot
   advance the authenticated close count.
   On a real worktree, absence of `.git`, HEAD, local main, the required hook,
   or the tracked checkpoint fails closed. Only a typed isolated engineering
   fixture may omit those surfaces, and it has no scientific authority.
6. If an active Job or Repair exists, resume or dispose it before opening work.

## Goal Intake

- Treat `OPERATING_DIRECTION.md` as the persistent Project Goal.
- Accept bare `/goal` or `/goal <one sentence>`. Do not require the user to
  provide IDs, hashes, scope arrays, terminal fields, or a structured manifest.
- If a Mission is active, resume it. Never open a parallel or replacement
  Mission.
- At the Mission-admission boundary, derive a compact ASCII manifest and open
  the first Mission or the exact predecessor-bound successor authorized by
  state. Never accept a user-supplied or unverified predecessor link.
- After a real Mission opens, route the exact `record_research_intake` action
  through `$run-research-portfolio`. Do not open its first Initiative until the
  writer accepts the head-bound intake record.
- Preserve immutable terminal, identity, duplicate, exposure, holdout, and
  scoped negative-memory history across Missions, including the reveal count
  and any future-holdout latch. Do not promote a candidate, claim, Release, or
  exhaustion credit from a predecessor automatically.

## Route

1. Classify the request before mutation.
2. Keep at most one active Mission under the persistent Project Goal. Resume it
   before considering successor admission.
3. Route data, Study, Batch, Executable, Lineage, trial, source, candidate, and Portfolio work through `$run-research-portfolio`.
4. Route ONNX, MQL5, MQH, EA, MT5, parity, materialization, and Release work through `$prove-runtime-release`.
5. Require the domain skill to return bounded evidence and a proposed Decision.
6. Let `axiom_rift.operations.writer.StateWriter` alone commit the Decision and next action.

Exact research boundaries are mandatory: Mission intake precedes the first
Initiative, `review_study_continuation` decides every eligible intermediate
Batch boundary, `diagnose_study` follows every real Study close and Git
checkpoint, and `review_architecture` precedes another Portfolio Decision when
triggered. A pending continuation, diagnosis, or architecture review blocks
unbound scientific work.

## State And Capability Rules

- Keep exactly one structured next action at stable boundaries.
- Permit only one active parent Job; declared workers must have disjoint inputs, outputs, and resource claims.
- Treat worker IDs, inputs, resources, and work-shard output labels as portable
  case-fold-unique logical claims. Worker output claims partition internal work;
  they are not aliases for, and need not be a subset of, declared Job files.
- Issue typed permits before engines run and revalidate them at engine boundaries.
- Engine reads open a Journal-authenticated SQLite read-only, query-only
  snapshot under the existing Writer lock. Workflow projection reads use the
  same no-mutation SQLite mode and retain their typed stable-head decision
  guard. Readers never create control, Journal, lock, index, schema, migration,
  or SQLite sidecar state; a missing or old projection fails closed for Writer
  recovery.
- Lazily load the local signing key through `PermitKeyStore(local/permit.key)`
  when the first Mission needs permit authority; never place the key in Git.
- Do not let callers provide record hashes or unrestricted state patches.
- Resume a started Job by immutable Job identity; never replay its one-shot permit.
- Bind Job attempts to the active Mission. Reuse success only when the exact
  expected-output and storage-class contract matches and every durable or
  reproducible output remains present with its declared hash. Transient output
  success is not reusable. Observe reusable success without changing control,
  next action, Journal, index, or operation records.
- Give every Job output and log one normalized relative ASCII POSIX logical
  name. Reject parent, drive, colon, backslash, reserved-device, and case-fold
  aliases. Keep durable evidence below `evidence/`, `scientific/`, or `source/`,
  reproducible cache below `local/cache/`, and transient output and logs below
  `local/jobs/`; completion repeats the exact declared names and classes.
- Bind every initial and retry Job implementation identity to a canonical
  `job_implementation_evidence.v1` manifest with sorted unique artifact hashes,
  and verify every referenced implementation artifact byte before declaration.
- For every production Job subject kind, require one exact recursive current
  `job_implementation_source_closure.v1` at declaration and start. Historical
  completions remain read-only evidence; replay labels, obligations, and
  fixture-looking protocols never exempt new execution authority.
- Keep scientific validator identity and operational execution authority
  separate. Validator identity binds its protocol, domains, implementation
  bytes, and explicitly authored semantic dependencies. A dependency that can
  change scientific meaning or verdict cannot be downgraded to closure-only.
  Registry sealing also infers and rechecks the complete current project import
  closure, but that operational closure belongs to future Job implementation
  identity. Genuine closure-only drift blocks or reidentifies future execution;
  it never retroactively reidentifies a scientific claim, validator verdict,
  Executable, trial, or historical result.
- After a failed attempt, use the Writer-derived `job_retry_family.v1`, not the
  caller's loose `input_hashes`, as the non-bypass retry boundary. An
  absent family stream triggers exactly one most-specific indexed legacy
  declaration lookup: the exact Batch slice when Batch-bound, otherwise the
  current-Mission slice. Rederive each stored family, join only its exact attempt
  head, and use the latest Journal authority sequence. Never globally scan Job
  or completion history, and fail closed on malformed or ambiguous history. An
  implementation retry still requires `job_changed_cause.v1`, the prior
  failure signature, changed implementation identity, and an actually changed
  artifact set without changing semantic inputs. It also requires a registered
  engineering validator to open the plan and every result artifact and
  independently establish exact `cause_resolved` and `material_change` facts;
  changed bytes, comments, caller prose, or a caller-written `passed` value are
  never repair authority. A same-implementation retry
  requires `job_retry_resume_authority.v1` bound to the exact current family
  completion, engineering disposition, resume condition, changed cause,
  information, or compute basis, and the same registered validation boundary.
  The Writer default registry is intentionally empty in production. When a
  repair is feasible, author and explicitly register the narrow validator that
  can recompute the exact resolution instead of abandoning the family or using
  the fixture validator. Bind its facts and registry trace into one deterministic
  `job-retry-basis`, consume that basis in the same `job_declared` event, and
  reject reuse or collision. Validator absence or failure remains engineering
  Repair evidence, never scientific rejection or axis exhaustion.
  Operational resolution evidence never enters semantic Job inputs. A compute
  reestimate changes only compute and wall bounds, preserves trial and stop
  semantics, receives no refund, and remains inside the cumulative original
  frozen Batch ceiling. Runtime-source ineligibility may resume without caller
  proof only when the Writer derives an unchanged Job spec and a fresh exact
  runtime-eligible source head replacing the failed state. A
  `requires_scientific_change` disposition leaves the family and creates
  distinct scientific work.
- Keep operational Job outcome separate from scientific verdict. A Job that
  produced and validated its declared outputs is operationally `success` even
  when the scientific validator returns `failed` or `not_evaluable`. Reserve
  operational failure for execution, engineering, source, runtime, or external
  failure, and never turn it into scientific falsification.
- At a stable Portfolio boundary, an accepted but unstarted Decision may be
  withdrawn only through its exact typed evidence-bound Writer transition.
  Historical scientific errors are corrected additively; never rewrite old
  closes, trials, or negative memories.
- An authority migration invalidates the active prospective scientific protocol
  binding. Rebind the exact registered protocol to the new authority manifest
  before declaring another scientific Job; same-authority duplicate activation
  is not work.
- Keep an authority-changing code checkpoint unpublished on local `main` while
  canonical control still binds its predecessor. Require an empty Git index,
  no tracked worktree change except the exact resumable correction suffix,
  `origin/main` as a strict nondivergent ancestor, unchanged baseline control
  and Journal blobs across `origin/main` and `HEAD`, and the exact reviewed
  authority replacement bytes at `HEAD`. Apply the typed correction, make its
  state and Journal suffix a second local commit, then deliver both commits with
  one non-force fast-forward push. For a segmented Journal, subtract the exact
  correction suffix already present after local `HEAD`, then prove that every
  remaining event in the two-event upper bound fits the current active segment
  even at the Journal event-size limit. Fail before correction mutation if it
  does not. This one-off delivery does not authorize segment rotation. Never
  publish the code checkpoint alone.
- Treat Git as recovery and delivery observation, never as state-transition authority.
- Route audit-created ReplayObligations through the writer as additive P0 or P1
  records with pending, in_progress, satisfied, or deferred state. Preserve the
  original event and apply the writer-derived effective evidence-scope and axis
  overlays. Match each new Executable to at most one exact original Executable;
  never bind by position, first trial, display order, or Study membership.
- Project an already canonical satisfied replay from its exact stored stream
  predecessor, same-event successful writer operation, immutable lineage, and
  recorded evidence identities. Do not rerun the current scientific validator,
  multiplicity protocol, or implementation bytes during an ordinary axis read.
  Current-protocol reinspection is authority only through the writer's explicit
  read-only satisfaction-invalidation plan.
- If that explicit audit proves an E01 family-size mismatch, cross-member family
  disagreement, or a self-consistent registration whose member set differs from
  the exact Batch set, bind the registration membership and hash and commit only
  the exact canonical evidence artifact through the writer. Preserve the old
  satisfaction, append satisfied-to-pending, add no scientific, trial, holdout,
  candidate, or terminal credit, and restore the replay scheduler constraint.
  The same member set in another historical order is a noncredit audit
  diagnostic, not scientific revocation authority. New prospective resolution
  still requires the exact canonical Batch-family order. A valid satisfaction,
  caller reason, malformed, missing, hash-forged, unrelated registration, or any
  other validation failure is not revocation authority.
- Require Component -> Executable -> Job implementation closure before a real
  Job declaration. Every participating Component binds current bytes and
  semantic dependencies, the Executable contains those identities, and Job
  artifacts cover their full recursive implementations. Reject historical modules with
  embedded Mission or Study identities as prospective implementations.

## Mandatory Study Close Delivery

Every real `study_closed` event is one coherent Git milestone and an immediate
delivery trigger.  Before any later Portfolio action, Study, Batch, or Job:

1. Require the writer-created immutable `study-kpi` record in the same Journal
   event. Validate that one new record and its close bindings from the bounded
   Journal suffix; do not render or scan prior KPI history.
2. Run focused checks for the closed Study and its disposition-driving evidence.
   When a
   repository-wide run is justified, use the Git-index-bound tracked-test
   manifest with exact path and byte hashes and report excluded untracked tests;
   do not let unrelated user files become acceptance authority.
3. On local `main`, stage only the exact Study milestone paths. They include
   `state/control.json`, the Journal path resolved from the staged snapshot,
   and the Study-scoped code, tests, or compact records that belong to the same
   closeout. A legacy snapshot resolves
   `records/journal.jsonl`; a segmented snapshot resolves its active segment.
   If the close rotates the Journal, also stage the changed manifest, the new
   seal, and the new active segment. Reject unrelated staged paths; never use
   blanket staging. Do not stage `records/STUDY_KPI.md` during routine close.
4. After staging state and the exact Journal suffix, run
   `scripts/update_study_close_delivery_checkpoint.py`, then stage the exact
   changed `records/STUDY_CLOSE_DELIVERY_CHECKPOINT.json`. The checkpoint must
   advance in the same commit; omission or a caller-authored substitute fails
   closed.
5. Create one commit whose final paragraph is exactly two contiguous lines:
   `Axiom-Study-Close: <event_id>` followed immediately by
   `Axiom-State-Revision: <revision>`. The tracked commit-msg hook must validate
   the bounded staged Journal suffix, control and index heads, the exact new KPI
   record, checkpoint transition, co-staged paths, and exact trailer block.
   Never use `--no-verify`. Then immediately attempt a
   non-force push of `main` to `origin/main`. Observe remote tree equality
   read-only when delivery succeeds.

A push, authentication, network, protection, or divergence failure never
rolls back the scientific close and never becomes scientific evidence or a
Mission blocker by itself.  Preserve the local commit, resolve delivery
without rewriting history, and retry the same commit at the next stable
delivery opportunity.  Do not manufacture a second closeout commit.  The
local commit and first bounded push attempt must precede later scientific
work; remote success itself is not a scientific gate.

After the checkpoint and first push attempt, route the writer-pending
`diagnose_study` action through `$run-research-portfolio`. Diagnosis interprets
the final bound evidence; it does not change the closed KPI or create evidence.

`records/STUDY_KPI.md` is a lag-tolerant navigation materialization, not close
authority. Refresh it only through explicit full maintenance at a useful stable
boundary, bind the refreshed digest in a maintenance checkpoint, and never make
its freshness a prerequisite for later valid science.

A sponsor-authorized historical KPI adoption is one coherent local-main
milestone, not one rewritten commit per old Study.  Require the typed
`study_kpi_backfilled` event, unchanged scientific state and counts, the exact
backfill trailer and state revision, then make the same immediate non-force
push attempt.

A sponsor-authorized delivery repair is one Git attestation checkpoint for an
exact list of already-delivered prospective closeout commits that omitted only
their trailers. Verify and record each original commit, tree, close event,
revision, and required-path blob IDs in
`records/STUDY_CLOSE_DELIVERY_REPAIR.json`. The checkpoint uses
`Axiom-Study-Close-Delivery-Repair` and `Axiom-State-Revision` trailers, changes
no scientific state or KPI, does not rewrite history, and does not duplicate a
Study-close snapshot.

## Validation Economy

Choose validation in proportion to the changed reusable surface and the claim
at risk. Focused checks and the fast bounded checkpoint guard are the routine
path. A tracked full suite, complete-history reconstruction, or exact-staging
audit belongs to a coherent engineering or delivery milestone and is not a
per-Job prerequisite. Do not delay an otherwise permitted bounded scientific
Job for unrelated slow validation. Test success remains engineering evidence.

## Repair

Freeze scientific identity and counts. Record cause, minimum reproduction,
changed-cause proof, and resume target. Make the smallest coherent engineering
change, validate the affected surface, and resume the interrupted action. A
failed Repair attempt does not abandon a feasible recovery: preserve it as
engineering evidence and try another bounded Repair only when cause, input,
implementation, or information state materially changed. If scientific
semantics change, stop calling the work Repair and register a new Executable.

Use the typed attempt stream rather than treating an arbitrary artifact as a
successful Repair. `open_repair` requires an exact engineering failure. Each
`running_job_repair_attempt.v1` extends the active Repair's prior attempt and
basis, names one changed dimension, binds the original reproduction, carries
disjoint changed and verification evidence, and states `failed` or `repaired`
without changing scientific semantics. Record a failed attempt with
`record_failed_repair_attempt`; it keeps the Repair active. Close a successful
attempt with `close_repair`. An implementation attempt also carries the exact
`running_job_implementation_repair.v1` closure proof. Fixed-hold replay proof
materializers require the independent verification evidence hashes and return
the outer attempt proof accepted by `close_repair`.

For a production Executable-bound implementation Repair, a caller-authored
`scientific_semantics_changed: false` is never closure authority. First use the
writer's read-only semantic-equivalence plan. Close in place only through
`running_job_implementation_repair.v2`, whose content-addressed plan, result,
measurements, old and new implementation manifests, and complete artifact sets
are opened by the dedicated registered scientific-domain validator. The writer
derives the exact callable, protocol, active evidence-binding, decision,
lifecycle, cost, source, component, and claim surface inventory and requires a
passed verdict with full claims, exact measurements, and an immutable registry
trace. The generic safe method is narrower than behavioral equivalence: both
implementations must contain one exact `job_implementation_source_closure.v1`
that explains the complete outer artifact set, preserves callable and relative
path inventory, and binds every changed path to its exact old and new hashes.
The validator compares the opened bytes at each changed `.py` path by canonical
Python AST; it does not parse the changing closure JSON as source. Thus comments
or layout may change, while changed syntax, a path swap, a hash-set-only
manifest, missing or ambiguous path roles, or changed non-Python bytes cannot
pass this generic route. Behavior-changing code needs a protocol-specific
validator or a new scientific identity. Missing, failed, not-evaluable,
partial, unregistered, mutable, or self-authored-only proof remains a failed
Repair attempt and routes to `requires_scientific_change`; it never closes in
place. Engineering fixtures and non-implementation Repairs retain their
bounded existing path.

Do not impose a numeric Repair-attempt cap. End an unrecovered Repair only with
`conclude_repair_unrecovered` and one evidence-backed
`engineering_failure_disposition.v1`: `requires_scientific_change`,
`repair_infeasible`, `repair_nonpositive_expected_value`, or
`repair_exhausted_changed_causes`. The disposition lists every failed attempt
for the Job and an exact resume condition; changed-cause exhaustion needs more
than one attempt. Then complete the Job as `failed` with the same
`repair_disposition_hash`. In a fixed-hold strict chain, name failed attempt
operations `<member-stem>-repair-attempt-<ordinal>` and an unrecovered terminal
`<member-stem>-conclude-repair` so replay closeout preserves every attempt.

After the typed unrecovered completion, a started Batch can end for engineering
failure only through that exact completion's `stop_batch` Decision. Pass the
same completion to Study close. A `continue_batch` Decision keeps the Batch
open for another bounded Job or Repair path; it is never authority for
`engineering_failure`, `not_evaluable`, or `stopped_early` disposal. Preserve
pre-activation rows as read-only history rather than weakening this prospective
boundary.

## Terminal

- `completed_pre_live_handoff` requires a frozen candidate-bound Release and
  every evidence required by `contracts/runtime.yaml`. It is the only Mission
  outcome that completes the persistent API Goal.
- `closed_no_candidate` requires a credible diverse-frontier exhaustion audit,
  not a few failures, exact quota satisfaction, or a small budget limit. Every
  partial, invalid, or unresolved axis needs an evidence-bound disposition,
  replay, preservation, or reopen condition. The preregistered numeric floors
  and required modes remain immutable inside the Mission. Additive evidence may
  qualify a conclusion without rewriting that standard; an audit-discovered
  standard defect is bound into the exact successor Mission intake and its new
  standard. The terminal closes only the current Mission; keep the API Goal
  active and continue through the exact predecessor-bound successor.
- A genuine external blocker requires no safe in-scope substitute, exhausted
  recovery paths, an exact external change, and an exact resume action. Freeze
  one typed ordered recovery plan at the exact current Journal event. Judge
  each completed external Job before another path may start. A failed verdict
  advances only when indispensability, no substitute, and no contract-valid
  next action remain validator-derived; otherwise restore the stored Mission
  action without blocker credit. Only the final credit-bearing failed verdict
  may propose the blocker. A passed verdict restores the stored Mission action.
  A `not_evaluable` verdict also restores that action but contributes no
  blocker credit.
- Bind the recovery plan identity to its stable-boundary event. Continuations
  keep that identity. After a passed or `not_evaluable` restoration, a
  recurrent outage may use the same condition and path semantics only through
  a new plan bound to the new current Journal boundary; reject a stale plan.
- External unavailability must be derived by a registered external validator;
  caller failure prose cannot establish a blocker attempt.
- A blocker validator must also establish that the dependency blocks one exact
  Mission capability, is indispensable to every valid terminal, has no safe
  substitute, and leaves no contract-valid next action.
- At a genuine external blocker, keep the API Goal active and wait for the
  exact resume condition. Do not manufacture a successor, completion, or
  scientific failure while the condition is unchanged.
- `blocked_external` does not require a Portfolio snapshot when research never
  opened. Its close must preserve the typed resume condition and exact Mission
  action. Reenter only the same Mission from that exact wait boundary after a
  registered validator derives `passed` availability from durable evidence.
  Issue a fresh Mission authorization epoch, restore the preserved action, and
  add no trial, claim, holdout, candidate, Release, or scientific credit.
- Never create live or live-ready authority.
- A pending positive terminal may be withdrawn only by invalidating its exact
  frozen active Release through `release_disposed`; all unrelated transitions
  remain blocked.

Commit and push coherent milestones only. At completed pre-live handoff,
verify the local branch and `origin/main` observe the same final tree without
writing that observed commit back into state.
