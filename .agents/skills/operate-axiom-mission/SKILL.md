---
name: operate-axiom-mission
description: Operate the persistent Axiom Project Goal through one active first or successor Mission, including bare or one-line /goal intake, continuation, Decisions, Repairs, blockers, Mission terminals, reentry, closeout, and Git observation. Use for /goal or any request that may change canonical control state.
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

## State And Capability Rules

- Keep exactly one structured next action at stable boundaries.
- Permit only one active parent Job; declared workers must have disjoint inputs, outputs, and resource claims.
- Issue typed permits before engines run and revalidate them at engine boundaries.
- Lazily load the local signing key through `PermitKeyStore(local/permit.key)`
  when the first Mission needs permit authority; never place the key in Git.
- Do not let callers provide record hashes or unrestricted state patches.
- Resume a started Job by immutable Job identity; never replay its one-shot permit.
- Bind Job attempts to the active Mission. Reuse success only when the exact
  expected-output and storage-class contract matches and every durable or
  reproducible output remains present with its declared hash. Transient output
  success is not reusable. Observe reusable success without changing control,
  next action, Journal, index, or operation records.
- Bind every initial and retry Job implementation identity to a canonical
  `job_implementation_evidence.v1` manifest with sorted unique artifact hashes,
  and verify every referenced implementation artifact byte before declaration.
- After a failed attempt, accept only a canonical changed-cause manifest bound
  to the prior failure signature, previous and new implementation identities,
  a canonical implementation manifest, and every referenced implementation
  artifact byte hash. Budget or timeout edits do not reset failed-attempt
  equivalence, and an implementation retry must change the actual artifact set.
  Input or scientific semantic changes use a distinct Job or Executable identity.
- Treat Git as recovery and delivery observation, never as state-transition authority.

## Mandatory Study Close Delivery

Every real `study_closed` event is one coherent Git milestone and an immediate
delivery trigger.  Before any later Portfolio action, Study, Batch, or Job:

1. Require the writer-created `study-kpi` record and the matching row in
   `records/STUDY_KPI.md`.
2. Run focused checks for the closed Study and the KPI projection.
3. On local `main`, stage only the exact Study milestone paths.  They include
   `state/control.json`, `records/journal.jsonl`, `records/STUDY_KPI.md`, and
   the Study-scoped code, tests, or compact records that belong to the same
   closeout.  Reject unrelated staged paths; never use blanket staging.
4. Create one commit with `Axiom-Study-Close: <event_id>` and
   `Axiom-State-Revision: <revision>` trailers, then immediately attempt a
   non-force push of `main` to `origin/main`.  Observe remote tree equality
   read-only when delivery succeeds.

A push, authentication, network, protection, or divergence failure never
rolls back the scientific close and never becomes scientific evidence or a
Mission blocker by itself.  Preserve the local commit, resolve delivery
without rewriting history, and retry the same commit at the next stable
delivery opportunity.  Do not manufacture a second closeout commit.  The
local commit and first bounded push attempt must precede later scientific
work; remote success itself is not a scientific gate.

## Repair

Freeze scientific identity and counts. Record cause, minimum reproduction, changed-cause proof, and resume target. Make the smallest coherent engineering change, validate the affected surface, and resume the interrupted action. If scientific semantics change, stop calling the work Repair and register a new Executable.

## Terminal

- `completed_pre_live_handoff` requires a frozen candidate-bound Release and
  every evidence required by `contracts/runtime.yaml`. It is the only Mission
  outcome that completes the persistent API Goal.
- `closed_no_candidate` requires a credible diverse-frontier exhaustion audit,
  not a few failures or a small budget limit. It closes only that Mission; keep
  the API Goal active and continue through the exact predecessor-bound
  successor.
- A genuine external blocker requires no safe in-scope substitute, exhausted recovery paths, an exact external change, and an exact resume action.
- External unavailability must be derived by a registered external validator;
  caller failure prose cannot establish a blocker attempt.
- A blocker validator must also establish that the dependency blocks one exact
  Mission capability, is indispensable to every valid terminal, has no safe
  substitute, and leaves no contract-valid next action.
- At a genuine external blocker, keep the API Goal active and wait for the
  exact resume condition. Do not manufacture a successor, completion, or
  scientific failure while the condition is unchanged.
- Never create live or live-ready authority.
- A pending positive terminal may be withdrawn only by invalidating its exact
  frozen active Release through `release_disposed`; all unrelated transitions
  remain blocked.

Commit and push coherent milestones only. At completed pre-live handoff,
verify the local branch and `origin/main` observe the same final tree without
writing that observed commit back into state.
