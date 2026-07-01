# Axiom Rift Evaluation Contract

schema: axiom_rift_evaluation_contract_v1
status: seed_draft
encoding: ascii_only
audience: codex_only

## Purpose

Capture early evaluation rules for Project Axiom Rift.

This file is intentionally rough. It exists to preserve user intent before later refinement into
strict operating policy, metrics, gates, and validation workflows.

## Cost Model Seed

Broker commission must be modeled as zero for FPMarkets US100 evaluation.

Rules:

- commission_per_trade: 0
- synthetic_commission_allowed: false
- commission_stress_test_allowed: false
- spread_stress_test_allowed: true
- slippage_stress_test_allowed: true

Cost pressure experiments may widen spread or apply slippage shocks. They must not add synthetic
commission unless a later explicit decision record changes the broker/account cost model.

## Target Metrics Seed

The target system should aim for:

- 5 to 10 entry events per active trading day
- controlled monthly drawdown
- strong profit factor after realistic spread and slippage assumptions

Exact thresholds, aggregation rules, pass/fail gates, and reporting formats are not frozen in
this seed draft.

## Sizing Evaluation Seed

Early discovery should prefer fixed-lot evaluation to compare signal quality without compounding
or sizing distortion.

Later robustness and growth validation may use equity-percent sizing after candidate quality is
established.

The exact sizing rules are not frozen in this seed draft.

## Claim Boundary

This contract does not claim:

- candidate_selected: true
- evaluation_gate_frozen: true
- economics_pass: true
- runtime_authority: true
- live_ready: true

This seed preserves evaluation intent only.

## Refinement Needed

Later refinement should define:

- relationship to experiment_constants_contract
- relationship to kpi_ledger_contract
- fixed-lot discovery lot size
- equity-percent sizing rule
- monthly drawdown calculation
- profit factor aggregation window
- spread stress levels
- slippage stress levels
- entry count measurement rule
- promotion pass/fail gates
