# Replay Admission And Running-Job Repair Recertification Audit

date: 2026-07-17
status: correction_implemented_pending_canonical_execution
mission_id: MIS-0006
initiative_id: INI-0025
study_id: STU-0114
job_id: job:7a90d7ee07e54a87b750492882e2ebf7835902155b63348ff1fa498e51a6dbce
control_revision_observed: 5426
scientific_credit_delta: 0
candidate_delta: 0
holdout_reveal_delta: 0
trial_delta: 0

## Prior Admission And Authority-Migration Findings Preserved

The following earlier findings remain part of this audit.  The running-Job
Repair addendum below extends them and does not replace their authority.

canonical_baseline_revision: 5410
canonical_baseline_authority: 3e5638871b267d238077231265d92e091f6133449b3306b5c58aac39df98491b
prospective_authority: cc556acff292f71d35a16fd528f174b4f6bc3758b8aaf033a53e8a2df44b39ab
prospective_validator: validator:5323ccc0517a5c99d9352fba7146e231c69a748cd1f3cd81696232bc69b931a6

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
    `kind:record_id` references. This caused a late Study-open failure after
    preflight and Decision work. The runner and Writer now use typed record
    references, and the workflow applies the same prospective semantic-lineage
    registry before preflight or Decision admission.
12. Source-closure validation detected that `control_next_action.py` changed
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
    without a second Git guard. The corrected plan requires `-I -S`, seals the
    Python and PyYAML RECORD provenance, independently replays every event byte,
    checks self-hash, offsets, index count and digest, reauthenticates Git and
    the Study-close guard before and after evidence, and binds both operation
    ids to one immutable content-addressed core.
16. The corrected orchestrator still repeated the same 5410-event baseline
    reconstruction five times, reread the full Journal ten times, and invoked
    the full Git boundary ten times. One boundary launched hundreds of serial
    Git processes because every checkpoint and execution blob used separate
    `cat-file` and `show` calls. A profiled read-only plan took 250.6 seconds
    and an isolated apply exceeded ten minutes before evidence. The run now
    retains one independent shadow, reads the root Journal once, advances the
    verified snapshot with exact Writer events, and uses Git `cat-file --batch`
    for checkpoint, execution, state, and authority objects. The same read-only
    plan now takes 59.3 seconds, and the Mission skill makes the single-shadow
    and single-snapshot rule durable.
17. The activation contract said that apply never pushes, but its nested
    Study-close guard could fetch and attempt a push when an ignored local
    receipt was absent. Correction execution now binds a typed read-only
    observation to the exact code HEAD, tracked checkpoint digest and commit,
    and plan-bound `origin/main` commit. Writer reauthenticates that local
    observation before each transition without fetch or push. The actual remote
    remained at the predecessor commit throughout diagnosis.
18. The first successful isolated two-event apply exposed a false drift on
    prefix-two reentry. The durable core stores authority files in canonical
    path order, while revalidation compared them with the control document's
    presentation order. Binding construction now canonicalizes the inventory
    once, and a full durable-core rebuild test covers completed reentry. The
    rejected reentry appended no event and changed no canonical state.

### Preserved Authority Transition

- `contracts/operations.yaml`:
  `1a9aa120b9877563028597e2973b665736e954c3212405aea006cba3a4b62930`
  to `c8f085b06155ddc92b829154a3b0fdb669ca3f8c5ff5ab34811b2bf75b6ea1c6`
- `contracts/science.yaml`:
  `e9d6d917b1b6a1855f90a70d7053957f54f5f193ed096c4dee75618b7ca41283`
  to `c27c2328231edd236b28d7e4e45c1674fbcfc0e00231e0151f793c221dece33a`
- All other authority documents remain byte-identical.
- Canonical delivery is one old-to-final `authority_migrated` event followed by
  one `research_protocol_activated` event. Neither event is scientific evidence.

### Preserved Non-Bypass Invariants

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

### Preserved Verification Evidence

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

## Purpose

This audit follows the complete STU-0114 admission, replay-obligation,
running-Job, failure, Repair-proof, validation, resume, and CLI path.  It
separates engineering correction from scientific evidence and records both
resolved defects and the exact remaining execution boundary.

## Exact Correction Capability

- declared old implementation:
  `921d179ecc580391d144db48ea31d8ef45ddbf5a3330c689e77c9bf55bbdcdc9`
- registered repaired implementation:
  `7b86dbaf0f6e2e3bf48ba86b80e55eba54d870a2e6f9f5493c931bfd8c8ca730`
- registered validator:
  `validator:7a90f5cc1e74df0ba28264830120a83bd248c6b7a4a47b783ec8a7d9082a8af7`
- source closure: 56 exact project-local paths
- changed source paths: 7 exact paths
- changed symbol inventory: exact per-path AST definitions, not display names

The old-to-new pair is pinned outside the Job closure.  The validator identity
is pinned outside both the validator implementation and Job closure, avoiding
self-hash authority.

## Findings And Dispositions

### AX-RAR-001 Immediate-predecessor-only replay ancestry

The running-Job context expected one correction invalidation immediately before
the current progress record.  The actual valid route was invalidation at
stream 4, prior progress at 5, deferral at 6, resume at 7, and current progress
at 8.  This rejected valid resumed replay authority as malformed engineering
state.  The projection now walks and authenticates the exact ancestry.

disposition: resolved

### AX-RAR-002 V2 family-authority route mismatch

The v2 correction reused a previously accepted family authority, while part of
the reader assumed every family authority was created by the current
invalidation event.  The reader now distinguishes exact same-event creation
from authenticated prior-family reuse and rejects cross-event substitution.

disposition: resolved

### AX-RAR-003 Noncanonical invalidation inventory acceptance risk

V2 audit-manifest parsing did not preserve one exact canonical order boundary
for completion inventory and observations.  The parser now rejects reordered,
duplicated, or otherwise noncanonical inventory instead of normalizing it into
authority.

disposition: resolved

### AX-RAR-004 Lossy resume payload parsing

Resume-evidence reconstruction accepted a weaker shape than its identity
payload.  The parser now requires the exact field set and round-trips the exact
identity; additional or missing fields fail closed.

disposition: resolved

### AX-RAR-005 Generic V1 Repair could not prove the V2 authority correction

The only prior implementation-Repair proof admitted behavior-preserving Python
AST equivalence.  The required correction intentionally changed authority
projection behavior, so treating it as generic equivalence was either an
automatic rejection or a reward-hacking temptation.  A registered
protocol-specific validator now opens exact old and new closure bytes, checks
the bounded symbol changes, executes explicit conformance cases, and grants no
scientific or candidate eligibility.

disposition: resolved

### AX-RAR-006 Non-source implementation artifacts were discarded

Repair-plan closure comparison incorrectly treated the changed source closure
as the entire implementation artifact set.  Component and other non-source
artifacts could be lost or misclassified.  Old and new source closures are now
partitioned from the complete implementation artifact sets and the exact
non-source set must remain unchanged.

disposition: resolved

### AX-RAR-007 Caller-authored verification blob reward hack

The materializer previously accepted any existing evidence hash as external
verification.  The Writer now materializes or reopens one typed receipt and
recomputes its protocol, validator, implementation, source hashes, conformance
cases, and zero authority deltas.  An unrelated blob cannot become Repair
verification.

disposition: resolved

### AX-RAR-008 Producer and validator co-drift

The protocol-specific validator imported schemas, field sets, closure parsers,
and the final facts checker from the implementation being repaired.  A producer
change could therefore weaken its checker at the same time.  The validator now
owns independent literal schemas, field sets, canonical parsers, closure
partitioning, path comparison, surface identity reconstruction, and result
reproduction.  The target module is exercised as the subject, not trusted as
the validator contract.

disposition: resolved

### AX-RAR-009 Partial current-source TOCTOU guard

Only the seven changed paths were compared to current disk bytes.  An unchanged
source could drift between proof materialization and validation.  The validator
now freezes the complete 56-path inventory, opens every new source artifact,
compares every current source byte, and registers all 56 paths in the validator
pre/post dependency guard.  Resume also revalidates the complete current source
closure before the same Job re-enters its engine.

disposition: resolved

### AX-RAR-010 Dynamic identity auto-trust

The prior validator allowed any different old and new implementation identities
that used the named changed paths and symbols.  The exact old-to-new identity
pair is now pinned in the validator.  The final validator identity is pinned
independently in the Writer and the STU-0114 runner.  A body change under the
same symbol name cannot silently register itself as the correction.

disposition: resolved

### AX-RAR-011 Validation registration delayed non-validation work

The generic replay CLI registered the fixed Repair validator for plan,
study-close, and diagnose even though Repair uses a separate action.  It also
registered scientific validation for plan and diagnose, loaded a permit key for
diagnose, and validated malformed arguments only after Writer and design setup.
The CLI now uses an empty registry for plan and diagnose, scientific validation
only for study-close, fixed validation only for Repair, lazy permit keys, and
immediate argument rejection.  Writer imports of the fixed validator are lazy.

Measured local effects:

- Writer import cumulative time decreased from about 3.25 seconds to 0.66.
- malformed diagnose rejection decreased from about 9.15 seconds to 1.99.
- unnecessary fixed-validator sealing removed about 1.3 seconds per command.

disposition: resolved

### AX-RAR-012 Hidden Repair episode ceiling

The operation namespace silently rejected Repair episode 1000 and above.  A
positive integer episode is now canonical without an arbitrary upper bound.

disposition: resolved

### AX-RAR-013 Duplicated hidden Repair operation names

Repair operation IDs were embedded inside strict-chain inspection, encouraging
runner string duplication and drift.  A public typed operation-ID projection is
now the single namespace source for permit, open, attempt, close, conclude, and
resume operations.

disposition: resolved

### AX-RAR-014 Executable binding omission

The validator and downstream effective-implementation projection did not both
require the binding Executable to equal the validation plan and request
subject.  All three identities are now exact and a subject substitution fails
before evidence evaluation.

disposition: resolved

### AX-RAR-015 Conformance labels exceeded executed proof

Static case labels claimed a complete Writer or public-context proof while the
validator executed bounded parser and transition checks.  Case names now state
the exact exercised boundary, are accumulated only after each successful case,
and must equal the registered sorted case set.  Full Writer and public-context
authority remains an integration and canonical-execution obligation rather
than being implied by a label.

disposition: resolved

### AX-RAR-016 Remaining Portfolio plan projection cost

After validator-registration removal, read-only plan still takes about 8 to 9
seconds.  Profiling attributes most of this to effective-axis reconstruction:
thousands of authenticated record decodes and more than one thousand Journal
event reads, including historical cost authority.  This is not a reason to
weaken authority.  A stable-head-bound bulk projection or snapshot-local
authenticated-record memo is the next bounded optimization.

disposition: open_nonblocking_optimization

### AX-RAR-017 Canonical Repair and scientific replay are not implied

At this audit snapshot the active Job remains running at revision 5426 and no
active Repair exists.  Code correction and tests do not satisfy the replay
obligation or create scientific evidence.  The exact remaining route is:

1. open and close the typed fixed-hold Repair;
2. explicitly resume the same Job;
3. execute and close STU-0114 under the repaired protocol;
4. checkpoint and push the real Study close;
5. diagnose the Study and continue the research Portfolio;
6. perform the required second exhaustive audit after real research.

disposition: pending_canonical_execution

## Verification

Focused changed-surface suite:

- 162 passed
- 1 skipped for its pre-existing conditional environment boundary
- 23 subtests passed
- elapsed time: 78.90 seconds

The suite covers replay parsing and ancestry, v2 invalidation behavior, running
Job context, validator registration and dependency guards, generic and
protocol-specific Repair evidence, Repair operation chains, CLI stage-specific
capabilities, and both volatility and analog fixed-hold research surfaces.

This audit grants no scientific, candidate, holdout, Release, Mission terminal,
or Project Goal completion authority.
