# Atomic Scientific Proof Enforcement Audit

date: 2026-07-16
status: repaired_pending_activation
mission: MIS-0006
initiative: INI-0025
scope: prospective scientific adjudication v2 proof admission

## Finding

The active v2 proof helper emitted a generic summary proof for terminal
scientific evidence modes when no registered trace protocol was supplied.
The proof parser also accepted that generic envelope as an alternative to an
atomic execution trace. A manually assembled validation plan could therefore
bypass the helper and reach the same acceptance path.

The generic proof copied metric bindings from the measurement and verified its
own envelope, but did not independently replay the plan, atomic observations,
statistical calculation, execution clock, or result attribution required by
OD-AUD-021. This was a prospective evidence-admission defect, not evidence that
any historical result should be reinterpreted by itself.

## Root Cause

The proof schema remained useful as a historical summary representation, but
the prospective v2 acceptance boundary treated representation compatibility as
scientific capability. The builder and parser each failed open in a different
place, so repairing only one would leave either a manual-plan bypass or late
post-execution rejection.

## Repair

- Terminal scientific evidence modes require an explicit registered atomic
  trace protocol before proof requirements can be built.
- The parser accepts only the registered atomic trace and its bound independent
  calculation proof for terminal scientific modes.
- The generic summary schema remains readable but grants no prospective v2
  scientific acceptance.
- The exact audit-integrity proof pair remains the only protocol-free default.
- Existing registered analog-state and fixed-hold-family atomic paths remain
  compatible.
- Direct regression tests cover helper rejection, manually assembled summary
  rejection, validator rejection, audit-integrity compatibility, and registered
  atomic positive paths.

## Quant-Team Review

- Research lead: terminal scientific evidence cannot be accepted without the
  observations needed to reproduce the claimed mode.
- Quant validation: copying a reported metric into a proof envelope is not an
  independent calculation or multiplicity-aware adjudication.
- Data and causality: the repaired boundary preserves clock and availability
  observations in the registered atomic trace rather than trusting prose.
- Research operations: early plan construction now fails before a costly Job;
  completion validation independently blocks hand-written bypasses.
- Risk and governance: audit-only inspection remains available, while audit
  evidence cannot be promoted into causal, temporal, cost, or stress credit.

## Authority And Evidence Effects

The authority documents already require atomic proof, so no Project Goal or
contract wording changes are needed for this defect. The validator dependency
closure changes and therefore requires a typed superseding v2 research
protocol activation at the current stable Portfolio boundary.

scientific_trial_delta: 0
scientific_claim_delta: 0
holdout_reveal_delta: 0
candidate_delta: 0
historical_verdict_delta: 0
