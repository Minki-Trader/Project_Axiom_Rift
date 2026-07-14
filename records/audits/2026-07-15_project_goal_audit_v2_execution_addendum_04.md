# Project Goal Audit V2 Execution Addendum 04

status: stu0021_source_bound_replay_exactly_deferred_pending_two_p1
parent_report: records/audits/2026-07-15_project_goal_audit_v2_execution_addendum_03.md
mission: MIS-0006
historical_study: STU-0021
replay_obligation: historical-replay-obligation:218391cba288e0e97fba30047cc277de1339cd310338728058f976fbac4b0d89
deferral_id: historical-replay-deferral:907f0c9769f3cfcdbd4c56ad2bed2d98e2e9266d700821d97d98b2b86e366187
source_invalidation: source-authority-invalidation:dd725aa415230abec2f882be95654757b951bf854db4f3fff58561ea79cec01a
invalidated_source: source:5b1a2771e4eeb04dea645631645fc99d41783e0ce34fc5d40e95bc01ca79c1f7
reconstruction_source: source:e85f5282855aef4f106583343f8db635cc3b43a13ba4fb1fdaf5667ec4d2a103
deferral_revision: 5155
reconstruction_registration_revision: 5156
scientific_trial_delta: 0
holdout_reads: 0
candidate_claim_delta: 0

## Purpose

This addendum records why the remaining STU-0021 P1 replay must not be run
against its historical SourceContract and preserves one finite, exact resume
condition.  It is a scientific authority correction, not a negative verdict
on the cross-asset mechanism.

## Finding

All twelve original STU-0021 Executables bind
`source:5b1a2771e4eeb04dea645631645fc99d41783e0ce34fc5d40e95bc01ca79c1f7`.
That contract is permanently audit-invalidated because current broker history
cannot prove historical first availability, information completeness, or
original vintage.  Recomputing the family from the same current snapshot would
reproduce numbers but would not repair point-in-time authority.  Treating that
reconstruction as prospective scientific evidence would recreate the defect
that the Project Goal audit was required to remove.

## Bound Correction

The pending obligation is deferred against the exact durable source
invalidation.  Its resume condition binds all twelve original Executable
identities, all twenty original criteria, and the protocol
`python.source.cross_asset_downside_spillover_replay.v1`.  It may resume only
after a different SourceContract for the same canonical instrument reaches a
current `historical_audited` or `runtime_eligible` state.  A code label, current
content hash, or context-only registration cannot satisfy the condition.

The corrected reconstruction-only US500 contract was registered separately at
revision 5156 with state `context_only`.  It truthfully identifies the current
broker-history reconstruction while withholding historical performance and
point-in-time authority.  The registration did not resume the replay, create a
trial, alter the old evidence, or convert the source into candidate authority.

## Result

STU-0021 is no longer an ambiguous pending branch or a false scientific
failure.  It is a durable externally conditioned branch with one exact way
back into research.  STU-0017 and STU-0016 remain pending P1 obligations and
are not blocked by this source correction.  The Project Goal remains active.
