# Axiom Rift Experiment Constants Contract

schema: axiom_rift_experiment_constants_contract_v1
status: seed_draft
encoding: ascii_only
audience: codex_only

## Purpose

Capture fixed experiment assumptions for Project Axiom Rift.

This file is intentionally rough. It preserves baseline experiment constants before later
refinement into strict evaluation, tester, runtime-validation, and campaign policies.

## Fixed Market Surface

Baseline experiments use:

- symbol: US100
- timeframe: M5
- broker: FPMarkets

The active project already records the working data period, clean-period candidate, and
rolling-window split policy in registries. This seed contract does not redefine those periods.

## Baseline Account Assumptions

Baseline experiments use:

- initial_deposit: 500
- deposit_currency: USD
- leverage: 1:100

## Baseline Execution Assumptions

Baseline experiments assume:

- latency: none
- execution: ideal_fill
- commission: 0

This baseline execution assumption is for early experiment comparability. It is not a runtime
authority claim and is not a live-readiness claim.

## Stress Pass Separation

The baseline experiment may be followed by separate stress passes.

Allowed stress dimensions:

- spread_widening
- slippage_shock

Forbidden stress dimensions unless a later explicit decision record changes the cost model:

- synthetic_commission

## Claim Boundary

This contract does not claim:

- evaluation_gate_frozen: true
- economics_pass: true
- runtime_probe_completed: true
- runtime_authority: true
- live_ready: true

This seed preserves fixed experiment assumptions only.

## Refinement Needed

Later refinement should define:

- exact fixed-lot size for discovery
- exact tester deposit settings
- exact leverage handling in Python and MT5
- spread baseline source
- spread stress levels
- slippage stress levels
- mapping between Python simulation assumptions and MT5 Strategy Tester settings
