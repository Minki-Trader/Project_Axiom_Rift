# Project Goal Audit V2 Integration Addendum

status: integration_findings_repaired_pending_activation_and_p1_execution
parent_report: records/audits/2026-07-14_project_goal_audit_v2.md
parent_report_sha256: 1f86b0800bb4d4bf7b6d6b903cfbe70736da40d9efed437fce35b6fc3eb655bc
parent_control_revision: 4935
mission: MIS-0006
holdout_reads: 0
quarantine_reads: 0
scientific_trial_delta: 0
candidate_claim_delta: 0

## Purpose

The frozen V2 report identified the broad correction program. Adversarial
integration review then tested how those repairs interacted at crash, cache,
terminal, blocker, and reentry boundaries. This addendum preserves the later
findings without rewriting the frozen parent report or historical evidence.

## Integration Findings And Repairs

### V2-I01: completion scope was widened into axis-wide exclusion

An audit-only overlay is bound to one exact Job completion and removes all
scientific, economic, candidate, exhaustion, and terminal credit from that
completion. The first integration implementation incorrectly promoted that
fact into a permanent exclusion of the whole Portfolio axis. One corrected
historical completion could therefore hide later valid evidence or prevent a
repairable branch from being studied.

Repair:

- satisfied audit-only replay no longer blocks axis selection;
- open and preserved axes remain selectable;
- a historical prune that may have depended on the corrected completion is
  projected as requiring an explicit reopen decision while the snapshot stays
  immutable;
- source invalidation remains a hard blocker and cannot be cleared by an
  unrelated replay or overlay;
- historical adjudication readers cannot reintroduce credit removed by the
  exact completion overlay;
- no axis-wide zero-credit Mission-terminal exclusion exists.

### V2-I02: external recovery could preempt work and dead-end the Mission

An external Job could previously preempt unrelated next actions. Completed
external Jobs were not independently judged, not_evaluable results could count
as unavailability, a blocked Mission had no exact reentry transition, and a
Mission blocked before Portfolio construction could not close honestly.

Repair:

- external recovery begins only at a stable no-subordinate Mission boundary;
- one typed ordered plan binds the exact dependency, recovery paths, validator,
  required change, resume action, and current Journal boundary;
- every completion receives a standalone validator-derived judgement;
- only failed probe, local recovery, and safe-substitute paths support a blocker;
- not_evaluable restores the Mission action with zero blocker credit;
- blocked_external may close without manufacturing a Portfolio;
- exact passed change evidence reenters the same Mission with a fresh
  authorization epoch and rejects stale conditions, boundaries, and evidence;
- a recurring outage receives a new boundary-bound plan identity rather than
  being trapped by the earlier plan stream.

### V2-I03: evictable cache bytes were treated as durable authority

The P1 replay stored its neutral family trace under reproducible_cache, whose
contract permits eviction, but consumers and Study-close verification required
the local file to remain present. Normal cache eviction could therefore block a
valid replay or Mission progress.

Repair:

- the first subject trace durably contains the canonical neutral family bytes
  and strict producer manifest;
- consumers verify the exact producer completion, execution, trace, manifest,
  and hash before atomically rematerializing a missing cache;
- an existing hash mismatch or a missing or altered durable producer fails
  closed;
- Study close verifies durable traces and manifests and treats local cache
  absence as normal;
- cache presence never creates scientific or terminal credit.

### V2-I04: vectorized family evaluation preceded full trial registration

The first P1 Job evaluates the complete four-member concurrent family. The
initial operation order registered only the first Executable before that Job,
so a crash after its completion could expose four evaluated configurations
while durable trial accounting contained one.

Repair:

- all four exact family Executables are registered immediately after Batch open;
- no family computation or Job start occurs before all four registrations;
- the crash prefix therefore preserves exact Project Goal exposure even when
  later member Jobs have not completed;
- the historical exposure floor continues to exclude only these exact newly
  registered P1 identities and remains otherwise unchanged.

### V2-I05: permanent source invalidation created a terminal deadlock

An invalidated source axis correctly lost scheduler and terminal credit, but
the first effective-axis repair gave it no typed way to retire after a valid
replacement source and distinct axis were admitted. The Mission could neither
study the invalid axis nor remove its blocker honestly. A generic external
blocker could also have hidden this internal lineage gap.

Repair:

- one SourceReplacementLineage binds the exact old invalidation, old source,
  old axis, eligible replacement source-state record, replacement source, and
  distinct replacement axis;
- the old snapshot and permanent invalidation latch remain immutable;
- the old axis becomes retired_by_source_replacement, receives no scientific or
  terminal credit, and stops blocking terminal reasoning;
- between the retired and replacement pair, only the distinct replacement axis
  is schedulable, while unrelated eligible forest axes remain unaffected;
- an external wait is permitted only when its exact blocked capability is the
  unresolved source-replacement capability, and that wait creates zero
  scientific, exhaustion, or terminal credit.

### V2-I06: replay-constrained resume actions could not round-trip

The external recovery action originally accepted only flat scalar bindings.
The pending replay action requires an exact ordered obligation list plus its
priority, so an outage during P1 replay could not preserve and restore the
canonical next action without either weakening its binding or failing closed
forever.

Repair:

- resume bindings accept only canonical JSON-safe values and reject ambiguous
  or non-ASCII material;
- each supported action kind has an exact field and value-shape contract;
- ordered replay obligation identities and priority round-trip without lossy
  string coercion;
- restored control state must equal the original canonical next action exactly.

### V2-I07: family exposure safety was a runner convention

Registering all four P1 Executables before vectorized evaluation was corrected
in the runner, but the writer still allowed another caller to start a family
Job after registering only one member. The crash-safety invariant therefore
depended on one script rather than the engine boundary.

Repair:

- a typed ConcurrentFamilyManifest binds the evaluation mode and ordered unique
  exact Executable identities into the Batch identity and record;
- Job declaration and start both require every manifested family member to
  exist as a durable trial in that Batch;
- legacy and genuinely single-member Batches retain their prior behavior;
- retries and crash recovery recheck the same immutable family identity rather
  than inferring membership from display order or completed Jobs.

### V2-I08: activation planning mixed inspection with delivery mutation

The first V2 activation preflight called the full Study-close delivery guard
while it was still deciding whether the correction could apply. That guard may
fetch origin state or refresh local receipts. A nominal no-apply audit could
therefore mutate local delivery evidence. The activation also needed to prove
the exact old-to-new authority mapping, local-main boundary, checkpoint schema,
and parent/addendum provenance as one coherent basis.

Repair:

- pure planning performs only local read-only authenticated checkpoint and
  suffix inspection;
- network observation and receipt writes occur only in the explicit delivery
  readiness phase;
- every authority replacement row is exact, unique, complete, and bound to the
  frozen pre-V2 hash set;
- activation requires local main and the explicit authenticated v2 checkpoint;
- the frozen parent report and this addendum are both content-addressed, and
  the activation record binds this addendum while it binds the parent hash;
- a failed no-apply plan leaves canonical state and local delivery receipts
  byte-identical.

### V2-I09: cache verification could follow the wrong retry

Producer verification looked up the latest attempt with the same work
fingerprint. After a retry, a consumer manifest naming the earlier successful
producer could therefore be checked against a different declaration or
completion. This weakened exact provenance even when all payload hashes were
otherwise valid.

Repair:

- verification starts from the manifest's exact producer execution identity
  and its exact declaration;
- the deterministic start, permit stream, and engine-entry record must resolve
  to the unique completion of that exact manifest execution without relying on
  a latest same-work head or a success-only cache projection;
- execution, declaration, start, permit consumption, engine entry, trace, and
  output hashes are rejoined as one exact attempt;
- a later retry head cannot substitute for, validate, or invalidate the named
  producer attempt.

### V2-I10: a shared source outage could not enter an exact wait

The first source-replacement terminal repair allowed blocked_external only when
exactly one axis had exactly one unresolved source invalidation. One external
service can legitimately prevent several distinct replacement sources or axes
at once. Requiring a singular capability would leave that Mission unable to
close into a finite wait even after every local and safe-substitute path was
exhausted.

Repair:

- each unresolved invalidation retains its exact axis- and source-bound
  source-replacement capability;
- one unresolved capability retains its original identity, while multiple
  capabilities form a typed sorted unique capability-set identity;
- already completed replacement lineages are excluded from the pending set;
- the aggregate is permitted only when every terminal hard blocker is a source
  invalidation and no replay, scope, or other internal blocker is hidden by
  invalidation precedence;
- the external plan must bind the exact current singular or aggregate identity,
  and the resulting wait still creates zero scientific or terminal credit.

### V2-I11: exact-index testing omitted protected development prerequisites

The isolated tracked-test runner correctly excluded untracked test code, but it
also excluded every ignored file. Several tracked tests exercise the
Foundation-registered development loader and therefore require the exact
observed-development material and rolling split artifact. The runner reported those tests
as failures even though they passed against the same registered bytes in the
repository worktree. That false negative turned test isolation into a delivery
bottleneck and could misclassify valid code as broken.

Repair:

- the tracked index copy of `foundation/data.yaml`, never a caller path list,
  selects only the `observed_development` and `split_artifact` roles;
- each relative path is restricted to its exact approved `data/processed/`
  lane, and traversal, alternate-stream syntax, links, and junctions fail
  closed;
- declared SHA-256 and observed size are bound in the test manifest and are
  checked before, during, and after an independent opaque sandbox copy;
- missing or changed input bytes fail before acceptance rather than silently
  skipping or substituting data;
- the runner never parses market values or materializes the quarantined parent;
  the loader receives only the separately registered observed prefix;
- these protected bytes are an engineering test prerequisite only and create
  no scientific, candidate, exhaustion, terminal, or claim authority.

### V2-I12: a Component bundle digest had no durable artifact bytes

The forest replay Components used one domain-separated digest for an
implementation manifest that itself bound every participating source hash.
Job evidence finalized the source files, but not the exact domain-framed bytes
whose SHA-256 was named by each Component. The new implementation-closure guard
therefore rejected the otherwise complete lifecycle. Adding the digest to a
list without its real preimage would have hidden the defect rather than closed
the implementation chain.

Repair:

- the identity primitive exposes the exact deterministic domain-framed bytes
  already used by `canonical_digest`, without changing the digest of any
  unchanged domain and payload;
- forest replay exposes those bytes as a typed implementation-bundle artifact;
- production and fixture Job evidence finalize both the bundle artifact and
  every source dependency named inside it;
- the generic Writer closure parses a typed bundle, re-verifies each artifact,
  and recursively requires every bound dependency instead of trusting one
  dedicated runner convention;
- the bundle digest must equal the durable artifact SHA-256, and a label,
  caller-supplied digest, or source list without the exact bundle bytes cannot
  satisfy Component-to-Executable-to-Job closure.

### V2-I13: isolated testing copied the quarantined parent material

The first protected-input repair copied the complete registered processed file
into the pytest sandbox and merely labelled it as non-scientific. The normal
loader hashes that parent but places only the observed prefix in parser memory;
an arbitrary tracked test, however, could open the sandbox copy directly and
read or print quarantined tail values without a permit. A metadata flag is not
an access-control boundary.

Repair:

- Foundation registers a distinct content-addressed `observed_development`
  prefix with exact bytes, rows, time bounds, parent dataset, and split binding;
- the post-activation loader verifies and parses that prefix without opening
  the full processed parent, whose quarantined tail remains outside the test
  and scientific materialization path;
- a bounded engineering materializer hashes the complete parent only for
  sealed integrity and writes only the exact prefix before the quarantine
  boundary, never parsing or reporting tail field values;
- the tracked runner obtains its test list, Foundation bytes, and blob identity
  from one frozen index tree, then materializes only the observed prefix and
  split artifact;
- sandbox copies are read-only and both source and destination identities are
  rechecked in a `finally` boundary after recovery or pytest, so mutation cannot
  produce acceptance;
- the Foundation replacement activates through the same exact StateWriter
  authority migration as the V2 contracts; no direct authority edit or
  scientific credit is created.

### V2-I14: implementation closure stopped at direct facade modules

The first typed implementation bundle made its own bytes durable and required
every dependency named inside it, but the forest dependency inventory stopped
at direct adapters and facades. Executed delegates in analog fitting, proof
construction, validation, and shared chassis code were absent. Those delegated
files could therefore change while the forest Component retained the same
identity and its Job still passed the generic recursive artifact check.

Repair:

- the forest bundle closes the complete project-local semantic dependency graph
  reached by its declared execution roots, including delegated implementation
  modules rather than facade files alone;
- external libraries and non-executed typing imports are not misrepresented as
  project implementation bytes;
- the resulting dependency order and hashes are deterministic, unique, and
  durable through the same generic bundle-artifact recursion;
- mutation-sensitivity tests prove that changing a delegated semantic module
  changes the bundle identity and required artifact set.

### V2-I15: isolated Git metadata and host environment disclosed the source host

The protected parent was no longer copied, but `git clone --shared` left an
absolute source-object alternate and clone metadata inside the pytest sandbox.
The child also inherited almost the entire host environment. A tracked test
could use those runner-provided channels to recover the source repository path
or receive unrelated host credentials, defeating the intended isolation even
though the approved prefix copy itself was safe.

Repair:

- frozen-tree checkout is converted to a standalone sandbox Git snapshot before
  protected inputs or pytest are admitted;
- the sandbox is created outside the source repository ancestry, so ordinary
  parent traversal cannot re-enter ignored source data;
- source alternates, remotes, reflogs, and other source-path metadata are absent
  from the executable sandbox;
- the child receives a minimum explicit environment allowlist, while home and
  temporary directories are rebound beneath the sandbox;
- regression tests place source-path and secret sentinels on the host and prove
  that neither is available through sandbox Git metadata or inherited
  environment;
- the isolated runtime projection and tracked-byte postconditions continue to
  operate against the standalone snapshot.

## Authority Boundary

These findings are engineering and authority corrections, not scientific
results. This addendum creates no verdict, trial, candidate, holdout reveal,
Release, Mission terminal, or Project Goal completion. Canonical activation,
tracked verification, checkpoint delivery, and the prospective STU-0061 replay
must still follow their exact writer routes. The Project Goal remains active.
