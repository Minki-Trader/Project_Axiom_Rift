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
5. Require `git config --get core.hooksPath` to equal `.githooks`; run
   `scripts/install_git_hooks.py` when absent or different. At routine state
   boundaries let the Writer read-only authenticate
   `records/STUDY_CLOSE_DELIVERY_CHECKPOINT.json`, its exact bounded Journal
   suffix, the local-main checkpoint commit, and the retained delivery-attempt
   receipt. The routine guard must not fetch, push, refresh a remote ref, write
   a receipt, render the KPI Markdown view, or scan complete history.
   A missing, modified, or malformed checkpoint or receipt fails closed and
   routes to the exact explicit maintenance or delivery action; it never makes
   the routine guard perform that action implicitly. After a real closeout
   commit, run
   `scripts/update_study_close_delivery_checkpoint.py --attempt-origin` once
   for the bounded fetch/non-force-push attempt and retained receipt. A failed
   attempt records same-commit delivery debt but does not invalidate science.
   Initialize or upgrade the active v2 checkpoint only with the explicit full
   maintenance command. Historical backfill and sponsor-authorized trailer
   repair remain exact checkpoint-scoped exceptions; their complete-history
   proof is never a routine preflight. Close and no-close boundaries are
   monotone, and a no-close boundary cannot create another network obligation
   or advance the authenticated close count.
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
  reject reuse or collision. Validator absence, partial execution, or failure
  remains a zero-credit engineering Repair observation, never an accepted
  attempt, scientific rejection, or axis exhaustion.
  Operational resolution evidence never enters semantic Job inputs. A compute
  reestimate changes only compute and wall bounds, preserves trial and stop
  semantics, receives no refund, and remains inside the cumulative original
  frozen Batch ceiling. Runtime-source ineligibility may resume without caller
  proof only when the Writer derives an unchanged Job spec and a fresh exact
  runtime-eligible source head replacing the failed state. A
  `requires_scientific_change` disposition leaves the family and creates
  distinct scientific work only when a registered validator positively proves
  the semantic change; inability to validate is not that proof.
  After the predecessor Study closes and is diagnosed, a validated prospective
  non-replay successor routes back through the research Portfolio as typed
  `ProspectiveEngineeringReentry`. Do not leave it trapped behind a generic
  `preserve`-only diagnosis projection. The Portfolio must still compare the
  corrected same-axis work with a materially diversifying option through the
  plural quant-team review; Mission routing restores authority but never
  preselects the successor or grants scientific credit.
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
  correction suffix already present after local `HEAD`, require it to be an
  exact prefix of one content-addressed reviewed correction plan, then prove
  that every remaining event in that plan's frozen ordered inventory fits the
  current active segment even at the Journal event-size limit. A caller cannot
  choose or expand the numeric bound. Fail before correction mutation if the
  exact remaining inventory does not fit. This one-off delivery does not
  authorize segment rotation. Start the canonical apply directly under an
  isolated, no-site, no-user-site, environment-ignoring, safe-path Python
  process; a self-reexec from an unsafe parent is not authority. Bind and
  revalidate the exact resolved project import bytes plus the Python executable,
  implementation, version, and admitted PyYAML distribution RECORD provenance;
  use an empty private bytecode-cache prefix with bytecode writes disabled, and
  reject automatic startup modules, sourceless bytecode, native shadows, or
  import drift from the actual filesystem before mutation. Git ignore state is
  not execution authority.
  For every remaining event independently derive and core-bind the full
  semantic row and operation-result mappings. Independently derive the complete
  event control mapping and advance the projection record count and digest
  chain from the prior reviewed boundary. Independently advance the Journal
  sequence, predecessor, global offset from exact framed bytes, and event-ID
  chain as one pure envelope; the Writer and Journal shadows are not authority
  for those fields. Supply that exact canonical event to the Journal as a
  single-use preappend expectation before rotation, file open, or write; a
  mismatch or unused expectation leaves the Journal unchanged. Recovery may
  reuse a recorded timestamp only for exact byte replay after every durable
  input is materialized and read back. Never recover an unrelated baseline or
  arbitrary damaged projection: require the exact verified trailing correction
  event and a full authenticated match to its predecessor projection first,
  then admit and perform that recovery atomically under one Writer lock rather
  than calling generic recovery.
  Never publish the code checkpoint alone.
- Treat Git as recovery and delivery observation, never as state-transition authority.
- Route audit-created ReplayObligations through the writer as additive P0 or P1
  records with pending, in_progress, satisfied, or deferred state. Preserve the
  original event and apply the writer-derived effective evidence-scope and axis
  overlays. Match each new Executable to at most one exact original Executable;
  never bind by position, first trial, display order, or Study membership.
- Admit a multi-obligation replay only with one canonical member-assignment set.
  The full Batch family remains statistical authority, while each selected
  obligation progresses through exactly one original/prospective Executable
  pair and one target-specific family authority. Never schedule one identical
  complete family per sibling obligation.
- If pending siblings lack target-specific family authority, register all exact
  locally reconstructible authorities in one stable-boundary Writer event.
  This is zero-credit admission and must not alter the next action or justify
  serial per-member family execution.
- At a stable scheduler boundary, an already-computed omitted sibling may move
  pending to satisfied only through the Writer-derived additive recertification
  event. It binds a current accepted source satisfaction and rederives the exact
  closed member evidence with zero trial, candidate, holdout, or claim delta.
  Mixed valid and unresolved members are satisfied/deferred atomically.
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
  artifacts cover their full recursive implementations. Reject historical
  modules with embedded Mission or Study identities as prospective mechanism
  implementations. One exact reconstruction source is lineage data, not an
  exception, only when the active Writer-authenticated
  `HistoricalFamilyAuthority` already seals its path and SHA-256, the Job's
  registered validation plan binds the identical family and replay obligation,
  and the source contains only that original Study identity. Never infer this
  role from a filename, caller declaration, display text, or error message.

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
   Never use `--no-verify`. Then run
   `scripts/update_study_close_delivery_checkpoint.py --attempt-origin` for the
   one bounded fetch/non-force-push attempt and retained receipt. Observe remote
   tree equality read-only when delivery succeeds. Routine Writer preflights
   only authenticate that receipt and never repeat the network action.

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

Focused tracked tests materialize only the exact selected tests, the frozen
indexed `src/` tree, ambient pytest configuration and ancestor `conftest.py`
files, explicitly declared extra dependencies, and explicitly requested
protected inputs. They still report the excluded untracked-test inventory, but
they do not copy the full repository merely to run a small selection. Use
explicit full mode when repository-wide state is genuinely under test.

For one content-addressed correction run, reconstruct an independent complete
history baseline at most once and retain its exact replay session. Read the
canonical Journal snapshot once unless an explicit recovery observes a new
durable event, advance the in-memory snapshot only with byte-verified Writer
events, and batch immutable Git object reads. A correction apply may use a
typed plan-bound local Study-close delivery observation, but it must not fetch
or push before the exact state suffix has its second local commit; delivery is
the later single non-force fast-forward push required by the correction plan.

## Repair

Freeze scientific identity and counts. Record cause, minimum reproduction,
changed-cause proof, and resume target. Make the smallest coherent engineering
change, validate the affected surface, and resume the interrupted action. A
failed Repair attempt does not abandon a feasible recovery: preserve it as
engineering evidence and try another bounded Repair only when cause, input,
implementation, or information state materially changed. If scientific
semantics change, stop calling the work Repair and register a new Executable.
Revisiting an earlier basis is not itself an identical retry: an A-B-A route is
allowed only when the new candidate binds genuinely new material evidence that
no accepted attempt already consumed. Reject the exact repeated intervention
fingerprint and any reused basis supported only by old evidence.

Separate a proposed candidate, its independent evaluation, an accepted attempt,
and a zero-credit observation. `open_repair` requires an exact engineering
failure. A prospective `running_job_repair_candidate.v2` binds the active
Repair, Job, cause, last accepted basis and attempt, original reproduction,
changed evidence, verification receipts, implementation proof, explanation,
and resume action with disjoint evidence surfaces and frozen scientific
semantics. It contains neither a caller-authored outcome nor a caller-authored
failure observation. The Writer binds that candidate to one exact registered
validator, plan, and available registry trace through
`engineering_repair_evaluation.v2`; caller prose, a requested mode, changed
bytes, or a self-authored result is never evaluation authority.

Only `repaired` and `failure_reproduced` are accepted evaluation modes. A
`failure_reproduced` evaluation independently proves both the exact original
failure and a material change, then enters the failed attempt stream and
advances its accepted basis and head while keeping Repair active. A `repaired`
evaluation independently proves resolution and material change, then creates
the accepted attempt and close authority. The Writer may project these accepted
results through the existing typed attempt and close records. Pre-activation v1
attempts remain read-only history and cannot be upgraded into prospective
authority. Fixed-hold materializers build the exact candidate and protocol
artifacts; they never predeclare `failed`, `repaired`, or scientific change.

For a production Executable-bound implementation Repair, a caller-authored
`scientific_semantics_changed: false` is never closure authority. First use the
Writer's read-only semantic-equivalence plan. Close in place only through
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
validator or a new scientific identity.

`new_failure`, `invalid_change`, `not_evaluable`, and
`validation_unavailable` are zero-credit validation observations, not accepted
attempts. A partial validator result is not another mode; record it as
`validation_unavailable` with the typed `partial_validator_result` reason. A
`new_failure` observation requires a complete registered evaluation and one
candidate-bound `repair_new_failure.v1` manifest, but it still does not prove
the original failure, advance the accepted basis or attempt head, or contribute
exhaustion credit. An invalid, not-evaluable, unavailable, missing, mutable,
unregistered, or self-authored-only evaluation likewise cannot change the
Repair next action, close or abandon Repair, or change any scientific count,
claim, candidate, holdout, or Release authority. A later candidate extends the
last accepted basis and may bind the observation as genuinely new information.
Only a separate positive registered semantic-change proof can authorize
`requires_scientific_change` or creation of the corresponding new Executable;
failed or unavailable validation is never such proof. Engineering fixtures
remain non-production and have no scientific or prospective Repair authority.

Do not impose a numeric Repair-attempt cap. End an unrecovered Repair only with
`conclude_repair_unrecovered` and one evidence-backed
`engineering_failure_disposition.v1`: `requires_scientific_change`,
`repair_infeasible`, `repair_nonpositive_expected_value`, or
`repair_exhausted_changed_causes`. The disposition binds the exact accepted
attempt stream and the exact zero-credit observation stream separately, with
their stored traces and heads, and lists an exact resume condition. It cannot
flatten an observation into a failed attempt or exhaustion credit. Changed-cause
exhaustion requires independently validated material attempts over the exact
typed cause inventory, not one failed attempt, an observation count, or a
numeric cap. `requires_scientific_change` additionally requires the positive
registered semantic-change proof described above. Then complete the Job as
`failed` with the same
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
