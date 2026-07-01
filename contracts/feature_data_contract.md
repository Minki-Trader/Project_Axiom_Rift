# Axiom Rift Feature Data Contract

schema: axiom_rift_feature_data_contract_v1
status: seed_draft
encoding: ascii_only
audience: codex_only

## Purpose

Capture early feature-data rules for Project Axiom Rift.

This file is intentionally rough. It exists to preserve user intent before later refinement into
strict data availability, feature eligibility, and runtime reproducibility policy.

## Base Feature Rule

US100 closed M5 bars are the base decision frame.

External symbols may be explored as feature inputs, but only if they can be reproduced at the
relevant US100 closed M5 decision timestamp.

## External Symbol Seed

External symbols are allowed when their closed M5 data is available in time for each US100 M5
decision.

Examples of allowed exploration candidates may include:

- XAUUSD
- BTCUSD
- other broker-available symbols with timely closed M5 updates

The symbol name alone is not enough. Eligibility depends on actual data freshness and runtime
availability.

## Forbidden External Data

The following are not allowed as active runtime feature inputs:

- stale symbols
- delayed symbols
- batch-updated symbols
- symbols that freeze during relevant decision windows
- symbols that only fill historical data later
- symbols that cannot be refreshed in time for the US100 M5 decision

Research-only diagnostics using non-runtime data must be clearly marked as non-promotable and
must not be used for candidate promotion.

## Alignment Seed

External symbol features must be computed from their own closed M5 series and merged to the US100
closed M5 timestamp without future leakage.

Allowed principle:

- external_closed_m5_time <= us100_decision_time

Forbidden principle:

- external data that becomes known only after the US100 decision is treated as unavailable

## Claim Boundary

This contract does not claim:

- external_symbol_set_selected: true
- feature_set_selected: true
- feature_order_frozen: true
- runtime_feature_availability_verified: true
- runtime_authority: true
- live_ready: true

This seed preserves feature-data intent only.

## Refinement Needed

Later refinement should define:

- external symbol availability audit
- stale bar detection
- frozen symbol detection
- batch update detection
- missing external bar policy
- runtime refresh policy
- feature eligibility report format
