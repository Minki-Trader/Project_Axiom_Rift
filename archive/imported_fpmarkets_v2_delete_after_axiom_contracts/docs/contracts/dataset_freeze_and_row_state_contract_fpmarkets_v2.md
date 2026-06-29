# Dataset Freeze And Row State Contract

## Purpose

This contract defines how a v2 dataset freeze is identified, what row states mean, and which summary fields must exist before dataset evidence is treated as reusable foundation evidence.

This document supplements the three constitutional contracts. It does not override feature semantics, parser semantics, or MT5 handoff semantics.

## Required Freeze Identity

Every frozen dataset must define all of the following fields:

- `dataset_id`
- `window_start`
- `window_end_inclusive`
- `practical_modeling_start`
- `warmup_bars`
- `preload_policy`
- `weights_version`
- `feature_contract_version`
- `parser_contract_version`
- `feature_order_hash`

The combination of those fields is the minimum identity required for any reusable shared dataset artifact.

## Row State Definitions

- `valid_row`: a parser-level row whose required feature values exist and satisfy the contract surface on the `US100` base frame
- `invalid_row`: a parser-level row that remains inside the shared window but fails at least one contract requirement and therefore cannot become a model-input row
- `ready_row`: a runtime-level row that is already `valid_row` and also satisfies runtime readiness on the MT5 side for the same closed-bar timestamp

`ready_row` is not a promotion fact and not a trading-quality judgment. It is only a runtime-readiness state.

## Invalid Reason Taxonomy

Every `invalid_row` must carry at least one explicit reason code. The minimum taxonomy is:

- `warmup_incomplete`
- `main_symbol_missing`
- `external_alignment_missing`
- `session_semantics_missing`
- `numeric_invalid`
- `weights_unavailable`
- `contract_version_mismatch`

Implementation may carry more detailed subcodes, but every detailed reason must roll up into one of the required top-level categories above.

## Required Dataset Summary Fields

Every frozen dataset summary must record at least:

- `dataset_id`
- `window_start`
- `window_end_inclusive`
- `practical_modeling_start`
- `warmup_bars`
- `preload_policy`
- `weights_version`
- `feature_contract_version`
- `parser_contract_version`
- `feature_order_hash`
- `raw_rows`
- `valid_rows`
- `invalid_rows`
- `invalid_reason_breakdown`
- `source_identities`

## Operational Meaning

- no new alpha or range stage may treat a dataset as foundation evidence until this contract is satisfied
- placeholder dataset notes are not a freeze
- `valid_row`, `invalid_row`, and `ready_row` must never be used as interchangeable labels
