# Repair And Validator Boundary Audit

status: implementation_repaired_and_focused_integration_verified_pending_canonical_activation

## Scope

This audit covers the prospective engineering Repair path, failed-Job retry
admission, stored Repair episode authority, registered validator identity and
execution integrity, Writer lock placement, and the fixed-hold correction
route used by the completed historical replay campaign. It also checks that
engineering failure cannot create scientific failure, candidate, holdout,
Release, or terminal credit.

## Findings And Repairs

### AX-RVB-001 Outcome-bearing Repair admission

The legacy Repair attempt proof carried validation outcome fields and remained
reachable through duplicate prospective parsing and dispatch code. The Writer
now accepts only an outcome-free Repair candidate, runs its registered
validator outside the Writer lock, and consumes one unforgeable capability at
the unchanged control head. Legacy outcome-bearing parsing remains only for
fixture and historical read compatibility.

### AX-RVB-002 One failed attempt could erase a viable Repair forest

Repair history previously over-constrained basis reuse and could reject an
A-B-A investigation even when the later A attempt carried genuinely new
material evidence. Admission now rejects an exact repeated intervention
fingerprint and old-evidence reuse while allowing a prior basis to be revisited
with new information. A failed attempt advances only its Repair basis and does
not create scientific failure or abandon the Repair.

### AX-RVB-003 Validator unavailability could be mistaken for a verdict

Not-evaluable, partial, absent, drifted, or unavailable Repair validation now
records one typed zero-credit observation. It advances neither attempt count
nor scientific evidence. A later candidate may bind the exact observation and
its new-information artifacts without treating the observation as a failed
scientific trial.

### AX-RVB-004 Registered and legacy episode authority overlapped

Registered Repair episodes now use one authoritative reader. The duplicate
registered branch in the legacy replay validator and the dead prospective
attempt dispatcher were removed. Production stored attempts must carry their
outcome-free candidate authority; fixture-only historical compatibility fails
closed outside fixture scope.

### AX-RVB-005 Validator execution held or reacquired Writer authority

Job completion, retry admission, Repair candidate evaluation, semantic
equivalence, terminal Repair disposition, and external reentry validators now
run against a frozen dispatch outside the Writer lock. The commit rechecks the
exact control hash, request identity, manifests, and capability token and does
not rerun a validator while locked.

### AX-RVB-006 Permanent identity mixed science with operations

Authored semantic dependencies now bind their stable project-local transitive
closure, including classified deferred imports. Explicit semantic boundaries
separate registry, identity, and file-write infrastructure from permanent
scientific validator identity. Boundary paths remain in the runtime integrity
closure, so mid-process drift still fails before or after dispatch. This avoids
unnecessary protocol identity churn without weakening execution integrity.

### AX-RVB-007 Validation and projection work repeated unnecessarily

Content-addressed evidence reads, project import analysis, and stable
projection reads now reuse bounded content and source-graph caches while every
authority head and content digest remains checked. The representative
fixed-hold production Repair E2E fell from about 28.1 seconds before the repair
to 10.37 seconds in the final focused run.

### AX-RVB-008 Stored control fixtures lagged the Repair contract

The closed next-action fixture union omitted the disposition record identity
and the registered Repair authority and validation-scope fields. Fixtures now
exercise the exact production control schema rather than a permissive older
shape.

## Verification

- Repair, retry, candidate, episode, semantic-equivalence, and validator
  dependency integration: 146 passed and 29 subtests passed in 89.59 seconds.
- Full Writer surface: 97 passed and 75 subtests passed.
- Changed research, running-Job context, forest replay, implementation closure,
  and all chassis variants: 265 passed, 2 skipped, and 10 subtests passed.
- Component, storage, next-action, contract-admission, and audit-script surface:
  93 passed, 5 skipped, and 285 subtests passed.
- Validator semantic identity and execution-closure separation: 47 passed,
  1 skipped, and 5 subtests passed.
- Ten current production validator types sealed successfully against their
  permanent identities and full runtime integrity closures.
- Contract YAML parsed as ASCII mappings and the changed text surface passed
  `git diff --check`.

The skipped tests are existing conditional environment cases and did not hide
a failure on the changed Repair or validator surface.

## Authority And Completion Boundary

This audit grants no scientific, candidate, holdout, Release, Mission terminal,
or Project Goal completion credit. The changed authority files require one
typed canonical migration before repository operation. The repaired harness
must then run the current Portfolio decision through real research, and the
result must undergo the requested final exhaustive audit. Protected independent
TLT source work and the local projection were not modified by this audit.
