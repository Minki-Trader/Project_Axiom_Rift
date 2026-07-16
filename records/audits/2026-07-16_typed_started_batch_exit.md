# Typed Started-Batch Exit Audit

status: repaired_pending_activation
scope: prospective Batch disposal, Study KPI provenance, and legacy read compatibility
authority_boundary: additive_migration_and_protocol_rebind

## Finding

A started Batch could retain a `continue_batch` Job evidence Decision and then
dispose as `engineering_failure`, `not_evaluable`, or `stopped_early` without a
final disposition-driving `stop_batch` completion. The path discarded the exact
final completion identity from Study KPI provenance and allowed an operational
continuation judgment to become close authority.

Current Job completion already requires a typed unrecovered Repair disposition
for engineering failure. The residual defect was therefore a judgment and
provenance bypass, not permission to skip the typed Repair conclusion itself.

## Prospective Correction

- A started Batch without a final stop completion may use only exact frozen
  budget exhaustion as a Writer-derived unavailable close.
- Engineering, not-evaluable, and early-stop exits require exactly one final
  `stop_batch` completion.
- A typed unrecovered engineering completion requires the
  `engineering_failure` Batch outcome, and that outcome cannot bind another
  completion type.
- Study close must use the exact disposition-driving completion when one
  exists.
- A `continue_batch` Decision keeps bounded work or Repair open and cannot be
  converted into close authority.

## Historical Boundary

Immutable pre-activation KPI rows remain readable. Their legacy unavailable
reason is accepted only when its original Study-close authority sequence
predates the additive activation operation. No historical Study, Job, Batch,
trial, verdict, negative memory, or KPI row is rewritten.

## Scope And Credit

scientific_claim_delta: 0
trial_delta: 0
holdout_delta: 0
candidate_delta: 0
release_delta: 0
live_authority: false

