# Replay Family Batching And Sibling Evidence Recertification

Date: 2026-07-18
Mission: MIS-0006
Initiative: INI-0025
Scope: exhaustive-audit repair, no candidate or holdout authority

## Finding

The fixed-hold replay workflow attached one ReplayObligation to a Study while
executing the complete four-member concurrent family. A sibling obligation then
scheduled the identical family again. For the six remaining four-member P1
families this could expand 24 required member evaluations into 88 evaluations:
64 avoidable trials, or 72.7 percent overhead. The Writer also copied the
Study-wide obligation list onto every trial. That projection was harmless for a
singleton Study but ambiguous for a plural Study and could not prove exact
member lineage.

STU-0114 and STU-0115 had already executed all four family members successfully.
Their primary obligations were satisfied, while six sibling obligations stayed
pending solely because the historical Decisions selected only one obligation.
The sibling trials, V2 validator completions, synchronized multiplicity,
Study-close records, and diagnoses are exact and already durable. Rerunning
those six siblings would add compute and multiplicity without new information.

## Repair

1. A canonical ReplayMemberAssignmentSet binds every selected obligation to one
   original Executable, one prospective Executable, exact criteria, and one
   target-specific HistoricalFamilyAuthority.
2. The complete preregistered family remains Batch and multiplicity authority.
   An unselected control receives no obligation lineage.
3. Trial registration records only the exact member obligation. Historical
   singleton projections remain resumable; ambiguous plural full-list
   projections fail closed.
4. Decision, Study, Batch acceptance, implementation preflight, running-Job
   context, diagnosis, recovery, and terminal reconstruction bind the same
   assignment identity.
5. Mixed family outcomes are atomic: valid completed selected members become
   satisfied while only unresolved selected members become deferred.
6. A Writer-only sibling recertification transition derives satisfaction from
   current source satisfactions and exact closed evidence. It accepts no caller
   satisfaction and creates no trial, candidate, holdout, claim, or terminal
   credit. Source and target authorities must share the exact immutable family
   core and reconstruction source bytes.
7. Historical family source authority now binds a target-independent immutable
   family core plus an obligation-specific target. Membership, controls, source
   bytes, original Study, original Batch, and each historical trial remain
   exact.

## Existing Evidence Reused Without Compute

Source satisfactions:

- historical-replay-satisfaction:c1cdf96e6ac286e6825af9619f8cb893f5293ff5669969d0425735f038109f38
- historical-replay-satisfaction:3242ab3cd550fc71cff233f764b4e3071a741c8dd88636244835aaf88717e4c8

Derived sibling satisfactions:

- historical-replay-satisfaction:82b4ec64fa377d14ae503b54b2d759927197fd43aa7313c8e04fddad86a01d1e
- historical-replay-satisfaction:4dce1542aff5d10c2ed32d1de8a55eb044e1abc67b64a51698b69da90c7e798f
- historical-replay-satisfaction:3a6c0ae0fed3450637a7c5ecb4fa2780625afad07f365c51d477463eb49c2afb
- historical-replay-satisfaction:423f0c8d8a9dc272ffd8a65cc0b22e7a58971c9d5a6b34834ba6b6db32bdb4ef
- historical-replay-satisfaction:7b063c03a3b999624a1d0e2b806d37cc7dadec89aa086091b90ab6ee53da1a4f
- historical-replay-satisfaction:9e88b8ae31a5c81de1f4cc6965464c7fb49a3d66780b73715b83029640ef376c

The live authenticated index derived all six identities and accepted the full
current satisfaction protocol when the sole historical Decision-membership
omission was explicitly scoped. No scientific value, p-value, criterion state,
or outcome was copied from the primary member.

## Required Invariants

- Original records are immutable.
- One obligation maps to at most one prospective member.
- One prospective member maps to at most one selected obligation.
- Full-family registration precedes every Job.
- Current source satisfaction must remain the exact current Writer-authenticated
  head at recertification time.
- Every sibling must independently pass current criterion and multiplicity
  validation.
- Authority migration, protocol rebind, and sibling recertification are additive
  stable-boundary events.
- Scientific trial delta, candidate delta, holdout reveal delta, and claim delta
  are zero.

## Focused Proof

- Affected replay workflow, recovery, projection, implementation admission,
  runtime context, member lineage, family binding, and Initiative lifecycle:
  248 tests passed, one environment-specific test skipped, and 63 subtests
  passed.
- Authenticated live-index read-only derivation: 6 of 6 sibling satisfactions
  passed; pending P1 count projects from 23 to 17 with zero new trials.
- Isolated canonical shadow: authority migration, protocol activation, and the
  six-member recertification completed as revisions 5489 through 5491; record
  count moved 21675 to 21695 while trial count stayed 620, candidate count
  stayed zero, and the scheduler retained the same Portfolio decision.

This repair removes a systemic scheduling and lineage defect. It does not claim
that the remaining replay queue, later real research, or the second exhaustive
audit is complete.
