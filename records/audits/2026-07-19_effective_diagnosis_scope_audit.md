# Effective Diagnosis Scope Audit

status: accepted
date_utc: 2026-07-19
mission_id: MIS-0006
initiative_id: INI-0025
baseline_revision: 5708
baseline_event_id: f95050a5dca1ba2a956a20dfc1a0495f0fda612be35ccb513021ce8e525b7769
scope: complete_mission_diagnosis_inventory

## Finding

Study diagnosis read raw adjudication claims after additive completion-scope
authority had removed their scientific eligibility. This allowed an audit-only
frontier to retain confirmation debt and allowed two validity-invalidated
Studies to retain stale scientific bottleneck labels. Effective-axis projection
prevented direct candidate credit, but the diagnosis and Portfolio scheduler
still exposed false research authority.

## Complete Mismatch Inventory

1. STU-0105
   - diagnosis: diagnosis:023fcedeee24fc4882227ed37696ce05d7f537179a30895317d9797a771c26e7
   - current: supported_requires_confirmation
   - effective: not_identifiable
   - reason: audit_only_scope_cannot_create_scientific_confirmation
   - completion: cf799cf8e6d9cd16c8785d4f9dce500ed23cae440130b5c5c0bf84c6734b7d04
   - overlay: historical-evidence-scope:10ba053123fb6697ee4c839a491161d0206e6a4855367438c5c48c2294784ff4
2. STU-0107
   - diagnosis: diagnosis:abfbd5546a3849022bbeb311dab2c62f1e340ab7c4ad996f172bcd8a6c069fd2
   - current: absent_information
   - effective: not_identifiable
   - reason: completion_scientific_validity_invalidated
   - prior correction: diagnosis-correction:50e00faa0521b72ce89b3a4f5b209248568ebb8f8a91e22f4db4a630bf8dc0a1
   - disposition-driving completions: 4
   - every completion has one current scientific-validity invalidation
3. STU-0108
   - diagnosis: diagnosis:77601b1a26e73567017a5462b275d670847b893fbfb165b325486d34e4d26234
   - current: stability_concentration
   - effective: not_identifiable
   - reason: completion_scientific_validity_invalidated
   - prior correction: diagnosis-correction:37bd6153a543fce121a1f3b318123ff4e65d36a43130cca22a25c35cf4127091
   - disposition-driving completions: 4
   - every completion has one current scientific-validity invalidation

No other effective MIS-0006 Study diagnosis differs from the corrected rule.

## Quant Team Review

- Causality: an audit-integrity result establishes reconstruction only. It does
  not identify a prospective predictive or economic effect.
- Statistics: after effective scope is applied, none of the three Studies has a
  disposition-driving completion with scientific credit. A positive or
  bottleneck-specific diagnosis is therefore not identified.
- Data and provenance: the audit-only overlay and all eight validity
  invalidations are content-addressed additive authorities. Original closes,
  adjudications, claims, trials, and replay resolutions remain immutable.
- Execution and economics: all affected completion scopes have zero economic,
  candidate, and terminal credit. No PnL or KPI value can compensate for that
  authority boundary.
- Risk and architecture: removing stale confirmation or bottleneck labels does
  not prune a causal axis by itself. The next Portfolio decision must dispose,
  contrast, rotate, or select a genuinely scientific mechanism using effective
  axis state and opportunity cost.

The lenses agree on one non-compensating decision: preserve exact diagnostic
claims, project all three diagnoses as not_identifiable, and create no trial,
holdout, candidate, replay-satisfaction, or terminal delta.

## Systemic Repair

- Project every primary completion through current effective evidence scope
  before claim-scoped diagnosis.
- Exclude audit-only and validity-invalidated completions from scientific
  adjudication when eligible completions remain.
- If no eligible completion remains, preserve the diagnostic claim inventory
  and emit a typed not_identifiable reason instead of confirmation debt.
- Require credit and eligibility to agree and reject duplicate or malformed
  completion scope.
- Record the historical mismatch set through the existing complete-inventory
  additive correction route.
- Permit a later evidence-scope correction to append after one prior correction
  only when it binds that exact predecessor correction and audit. A prior
  correction is not a one-shot cap and is never rewritten.

## Validation Harness Finding

The historical revision-5410 replay-admission test reconstructed its frozen
predecessor from the moving origin/main ref and attempted to execute the old
validator activation through the current Writer. After normal project progress,
that produced four false failures before reaching the test subject. The test now
opens the content-addressed historical core, takes predecessor and prospective
bytes from the commits sealed by that core, verifies both recorded full event
envelopes and receipts, and checks tampering without treating current code or a
moving remote ref as historical authority. This removes a recurring validation
bottleneck without weakening recorded-event integrity.

## Verification

- 53 focused diagnosis, evidence-scope, effective-axis, and research-boundary
  tests passed.
- 81 grouped correction-core, historical-envelope, diagnosis, evidence-scope,
  effective-axis, and research-boundary tests passed, plus 3 tamper subtests.
- Exact correction modes reject non-isolated startup, and the apply path has one
  baseline reconstruction with no nested full-suffix preview.
- The authenticated revision-5708 MIS-0006 inventory derives exactly the three
  mismatches above and no unexpected projection errors.

## Credit Boundary

scientific_trial_delta: 0
holdout_reveal_delta: 0
candidate_authority_delta: 0
replay_satisfaction_delta: 0
historical_events_rewritten: false
