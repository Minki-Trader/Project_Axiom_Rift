---
name: operate-axiom-mission
description: Operate the persistent Axiom root Mission from a short goal through Initiatives, Jobs, Decisions, Repairs, blockers, terminal disposition, and Git observation. Use for /goal, continuation, next-action selection, state transitions, reentry, closeout, or any request that may change canonical control state.
---

# Operate Axiom Mission

Use the repository as authority. Do not depend on chat history.

## Boot

1. Read `AGENTS.md`.
2. Read `state/control.json`.
3. Read the active record named by control state, if any.
4. Read only the contracts required by the classified action.
5. If an active Job or Repair exists, resume or dispose it before opening work.

## Route

1. Classify the request before mutation.
2. Keep one root Mission for one user goal until a valid terminal.
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

## Repair

Freeze scientific identity and counts. Record cause, minimum reproduction, changed-cause proof, and resume target. Make the smallest coherent engineering change, validate the affected surface, and resume the interrupted action. If scientific semantics change, stop calling the work Repair and register a new Executable.

## Terminal

- `completed_pre_live_handoff` requires a frozen candidate-bound Release and every evidence required by `contracts/runtime.yaml`.
- `closed_no_candidate` requires a credible diverse-frontier exhaustion audit, not a few failures or a small budget limit.
- A genuine external blocker requires no safe in-scope substitute, exhausted recovery paths, an exact external change, and an exact resume action.
- External unavailability must be derived by a registered external validator;
  caller failure prose cannot establish a blocker attempt.
- A blocker validator must also establish that the dependency blocks one exact
  Mission capability, is indispensable to every valid terminal, has no safe
  substitute, and leaves no contract-valid next action.
- Never create live or live-ready authority.
- A pending positive terminal may be withdrawn only by invalidating its exact
  frozen active Release through `release_disposed`; all unrelated transitions
  remain blocked.

Commit and push coherent milestones only. At a requested delivery terminal, verify the local branch and `origin/main` observe the same final tree without writing that observed commit back into state.
