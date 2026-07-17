# Replay Admission And Recertification Audit

date: 2026-07-17
scope: historical replay admission, partial-prefix recertification, terminal,
replacement, resume, semantic lineage, restart, and authority delivery
scientific_credit_delta: 0
canonical_baseline_revision: 5410
canonical_baseline_authority: 3e5638871b267d238077231265d92e091f6133449b3306b5c58aac39df98491b
prospective_authority: cc556acff292f71d35a16fd528f174b4f6bc3758b8aaf033a53e8a2df44b39ab
prospective_validator: validator:5323ccc0517a5c99d9352fba7146e231c69a748cd1f3cd81696232bc69b931a6

## Findings Corrected

1. Missing or stale prospective protocol authority was incorrectly capable of
   becoming a scientific or replacement terminal. It now requires an additive
   protocol rebind followed by exact implementation recertification.
2. A legacy registration-only replay prefix lacked one authenticated admission
   boundary. The v2 admission now binds the Study, Batch, full frozen family,
   exact counted prefix, current protocol activation, current authority digest,
   scientific surface, source closure, and accepted preflight in one Writer
   event.
3. Existing counted trials could be refunded, recounted, or accepted from weak
   projection evidence. The shared inspector now recomputes Executable identity,
   Study lineage, trial flags, material accounting, cumulative multiplicity,
   Writer operation result, and Journal event authority.
4. The Writer confused the obligations advanced by one target trial with the
   Study's immutable full replay lineage. Non-target family trials now preserve
   the full Study obligation list while advancing no unrelated obligation.
5. A replacement deferral confused fresh prospective Executable identities with
   historical reference identities. The two families now bind through an exact
   one-to-one manifest mapping.
6. A deferred replay was revalidated as if its current head were still pending.
   Replacement and resume now authenticate the exact pending predecessor of the
   current deferred head.
7. The replacement Writer branch referenced projection symbols that were not
   imported. The path now fails by typed transition rather than NameError.
8. Later additive contract improvements could cause one-off validators to demand
   document rollback. Validators now recognize the exact materialized semantics
   while preserving their original predecessor-to-successor checks.
9. Replacement admission incorrectly required the non-evaluated baseline
   comparison anchor to be one of the counted family trials. The Writer now
   keeps the baseline and replacement family distinct while requiring a
   non-empty, unique, typed family and exact axis and provenance bindings.
10. An accepted replacement Decision lost its diagnosis, architecture-review,
    and continuation context when rebuilt after process restart. The exact
    accepted Decision is now the durable fallback, and any action-supplied
    context drift is rejected. The execute next action preserves the same
    context explicitly.
11. Semantic lineage mixed raw typed identities with the registry's required
    ``kind:record_id`` references. This caused a late Study-open failure after
    preflight and Decision work. The runner and Writer now use typed record
    references, and the workflow applies the same prospective semantic-lineage
    registry before preflight or Decision admission.
12. Source-closure validation detected that ``control_next_action.py`` changed
    after an isolated preflight was accepted. The isolated copy was restored
    only to prove the detector and was not admitted as canonical evidence.
13. The isolated replacement attempt also carried the invalid raw lineage basis.
    Its preflight, Decision, and Study permit are therefore unusable. No isolated
    control, Journal, trial, or scientific result is copied to canonical state;
    canonical preflight and Study execution must be derived again.
14. The Job declaration path introduced during the repair read a scientific
    lineage variable that was unassigned for an engineering fixture. The value
    is now initialized before the scientific-only branch, preserving the rule
    that engineering execution paths do not invent replay lineage.
15. A first activation orchestrator draft admitted five delivery weaknesses:
    unsafe import startup, no full-event preappend expectation, missing Writer
    evidence payloads, weak partial-prefix checks, and evidence publication
    without a second Git guard. The corrected plan requires ``-I -S``, seals the
    Python and PyYAML RECORD provenance, independently replays every event byte,
    checks self-hash, offsets, index count and digest, reauthenticates Git and
    the Study-close guard before and after evidence, and binds both operation
    ids to one immutable content-addressed core.
16. The corrected orchestrator still repeated the same 5410-event baseline
    reconstruction five times, reread the full Journal ten times, and invoked
    the full Git boundary ten times. One boundary launched hundreds of serial
    Git processes because every checkpoint and execution blob used separate
    ``cat-file`` and ``show`` calls. A profiled read-only plan took 250.6
    seconds and an isolated apply exceeded ten minutes before evidence. The
    run now retains one independent shadow, reads the root Journal once,
    advances the verified snapshot with exact Writer events, and uses Git
    ``cat-file --batch`` for checkpoint, execution, state, and authority
    objects. The same read-only plan now takes 59.3 seconds, and the Mission
    skill makes the single-shadow and single-snapshot rule durable.
17. The activation contract said that apply never pushes, but its nested
    Study-close guard could fetch and attempt a push when an ignored local
    receipt was absent. Correction execution now binds a typed read-only
    observation to the exact code HEAD, tracked checkpoint digest and commit,
    and plan-bound ``origin/main`` commit. Writer reauthenticates that local
    observation before each transition without fetch or push. The actual
    remote remained at the predecessor commit throughout diagnosis.
18. The first successful isolated two-event apply exposed a false drift on
    prefix-two reentry. The durable core stores authority files in canonical
    path order, while revalidation compared them with the control document's
    presentation order. Binding construction now canonicalizes the inventory
    once, and a full durable-core rebuild test covers completed reentry. The
    rejected reentry appended no event and changed no canonical state.

## Authority Transition

- ``contracts/operations.yaml``:
  ``1a9aa120b9877563028597e2973b665736e954c3212405aea006cba3a4b62930``
  to ``c8f085b06155ddc92b829154a3b0fdb669ca3f8c5ff5ab34811b2bf75b6ea1c6``
- ``contracts/science.yaml``:
  ``e9d6d917b1b6a1855f90a70d7053957f54f5f193ed096c4dee75618b7ca41283``
  to ``c27c2328231edd236b28d7e4e45c1674fbcfc0e00231e0151f793c221dece33a``
- All other authority documents remain byte-identical.
- Canonical delivery is one old-to-final ``authority_migrated`` event followed
  by one ``research_protocol_activated`` event. Neither event is scientific
  evidence.

## Non-Bypass Invariants

- Engineering failure is not scientific failure.
- Protocol migration is not evidence against a hypothesis.
- The baseline is a comparison anchor, not a counted replacement-family trial.
- Existing trial and multiplicity accounting is never refunded or recounted.
- Replacement uses a fresh full prospective family with unchanged historical
  scientific references.
- One rejected preflight can authorize at most one accepted replacement.
- Pending and in-progress terminals bind exact Study, Batch, close, diagnosis,
  preflight, deferral, resume, protocol, implementation, and lineage authority.
- A validator or source-closure failure is Repair evidence and cannot eliminate
  a research axis.
- No Job budget, scientific claim, candidate, holdout, terminal, or replay
  satisfaction credit is granted by recertification or this audit.

## Verification

- replay admission, correction, and dependent historical runner regression:
  170 passed, 258 subtests passed
- authority activation unit and full 5410-event shadow replay: 11 passed,
  3 subtests passed
- content-addressed correction, authority migration, and Study-close Git guard:
  74 passed, 1 skipped, 27 subtests passed
- shadow activation proves exactly two events, two replacement evidence
  artifacts, zero protocol evidence artifacts, exact preappend rejection, and
  no canonical control or Journal byte change
- profiled read-only activation planning fell from 250.6 seconds to 59.3
  seconds while retaining one full independent baseline reconstruction
- checkpoint and execution object reads are batch-bound, and the correction
  delivery observation has a zero-fetch and zero-push regression contract
- protected TLT work and the 2026-07-15 user audit are excluded from the code
  checkpoint and activation execution closure

## Remaining Project-Goal Work

This audit does not close the Project Goal. The authority activation, canonical
preflight, STU-0114 execution, Study-close delivery, diagnosis, systemic Writer
and Portfolio-forest improvements, prospective research proofs, and the final
post-run exhaustive audit remain required. A passing correction test is not a
scientific result and is not evidence that those remaining tasks are complete.
