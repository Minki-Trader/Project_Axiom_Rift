# Project Goal Audit V2 Execution Addendum

status: execution_findings_repaired_pending_next_p1
parent_report: records/audits/2026-07-14_project_goal_audit_v2_integration_addendum.md
parent_report_sha256: 052d3c039e811f7140bc54bf003eb0ff4def8d9db490e89d481cd152886ab82d
mission: MIS-0006
control_revision: 5020
control_event: 61da2fdb1930956b0acc9886042af09ca98eb70301e5394cfdaa922b58964fc2
study_close_commit: 55aa1bb694aa540c7a3caa5ead0518c7b18764d9
diagnosis_commit: 5fff3f0d93220ff61f1e14e5b8ad3bb74c4cdd44
holdout_reads: 0
quarantine_reads: 0
candidate_claim_delta: 0

## Purpose

The V2 correction was exercised through a real prospective STU-0048 replay,
not accepted from unit tests or static inspection.  This addendum records the
integration defects exposed by that execution and the reusable corrections
made before another P1 family is admitted.  Historical events and the completed
Study remain immutable.

## Execution Result

STU-0107 registered all four exact family members before computation.  Every
Job completed operationally, the current registered validator opened the exact
scientific proof inventory, and all twenty original criteria were recomputed.
The target scientific state was `partial_positive`, candidate authority stayed
false, and the STU-0048 ReplayObligation was satisfied only after Study-close
delivery and diagnosis.  The Study-close and diagnosis milestones are both on
local and origin main.  This result does not satisfy any other P1 obligation.

## Findings And Repairs

### V2-E01: a Job declaration accepted runner-specific schema drift

The first STU-0048 declaration supplied a custom historical-context field that
the canonical Job schema did not own.  The operation failed before a Job was
created.  The field was removed from the Job envelope; the registered trial
family and immutable Executable parameters now provide the context.

### V2-E02: validator upgrades could deadlock an unexecuted Study

The active protocol stream still named an earlier validator implementation.
Ordinary duplicate activation correctly failed, but no typed path existed to
supersede it after Study and Batch open and before the first Job.  The Writer
now permits only a same-authority, pre-first-Job validator replacement at that
exact boundary.  Any Job declaration closes the exception.

### V2-E03: implementation closure was complete in intent but unreadable

The Job implementation identity did not initially materialize a Writer-readable
canonical source-closure artifact.  The repaired route stores the exact closure
bytes plus every required Component source artifact.  Historical Study text is
allowed only when it is the exact original Study named by the active typed
ReplayObligation; current or unrelated hardcoded identities still fail closed.

### V2-E04: auxiliary cache provenance entered scientific proof inventory

Producer cache provenance is durable operational evidence, but the first
completion routed it as an additional scientific proof artifact.  The validator
therefore rejected a valid producer output set.  Scientific validation now
receives only the result, exact plan output, observation-bound measurement
outputs, and preregistered proof outputs.  Auxiliary durable outputs remain
verified completion evidence without gaining scientific authority.

### V2-E05: a partial Repair chain could masquerade as a complete resume

The shared workflow recognized any one of Repair permit, open, or close as a
reason to insert all three operations into its strict prefix.  It had no right
to invent the cause or changed-cause proof for missing steps.  It now accepts
only a complete successful exact Repair chain.  A partial chain stops at an
explicit resume boundary listing the missing operations.

### V2-E06: later trials could retroactively invalidate frozen context

The STU-0048 runner compared its frozen prior exposure count with every trial
outside the family, including trials registered after the Study.  Future valid
research would therefore make the completed replay unreadable.  The reusable
exposure projection now freezes the count at the authority sequence immediately
before the first family trial.  Later trials are irrelevant; incomplete,
duplicated, unordered, or context-divergent families fail closed.

### V2-E07: Portfolio bridging used a positional scheduler fallback

The replay workflow attached a new axis to `selectable[0]`.  That was stable
Python ordering, not quant-team judgment, and both completed replay bridges
therefore targeted the same unrelated first axis.  Future replay specifications
must name one exact currently selectable bridge axis.  Missing, duplicated, or
ineligible choices fail before state mutation.  Completed historical Decisions
are not rewritten.

### V2-E08: replay design cost grew with work history

Component reconstruction scanned trials, Decisions, Studies, and Portfolio
snapshots on every design build.  The exact same current axes reconstruct from
the compact `component-manifest` projection plus the prospective member
Executables.  On the revision-5020 snapshot this reduced the input projection
from 972 payloads to 447 and registry construction from about 0.697 seconds to
0.059 seconds while preserving all 35 axis identities.

## Verification Boundary

Focused regression verification passed 84 tests and 9 subtests.  A direct
authority-order check appended a synthetic later trial in memory and still
derived the STU-0107 frozen context as 578 at first-family sequence 4986.  No
canonical state, scientific trial, verdict, holdout, candidate, or Release was
created by these engineering checks.

The Project Goal remains active.  Five P1 ReplayObligations remain, and the
next one must be chosen by evidence value, source eligibility, identifiability,
compute cost, and Portfolio opportunity cost rather than obligation ordering.
