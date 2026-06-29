# Runtime Parity And Artifact Identity Contract

## Purpose

This contract defines the minimum fixture set, identity fields, and integrity fields required to close Python to MT5 runtime parity and artifact identity in v2.

This document supplements the three constitutional contracts. It does not replace feature semantics, parser semantics, or MT5 input-order semantics.

## Minimum Gold Fixture Set

The minimum reusable parity fixture inventory must contain all of the following:

- one regular closed-bar sample inside normal `US100` cash-session flow
- one session-boundary sample that exercises cash-open or cash-close semantics
- one DST-sensitive sample that proves `America/New_York` handling is stable across the contract surface
- one external-alignment sample that proves exact timestamp matching across required external symbols
- one negative fixture that proves a required-missing-input case resolves to non-ready behavior instead of silent degradation

## Required Identity Fields

Every parity and artifact-identity bundle must define at least:

- `dataset_id`
- `fixture_set_id`
- `bundle_id`
- `runtime_id`
- `report_id`
- `parser_version`
- `feature_contract_version`
- `runtime_contract_version`
- `feature_order_hash`

Those fields must match across Python snapshot, MT5 snapshot, and parity report outputs. Artifact registry entries that represent the same durable bundle must record the same identities in scalar registry columns, including `parser_version`.

## Required Feature, Order, And Hash Rules

- Python and MT5 snapshots must use the same frozen `58`-feature order
- the same `feature_order_hash` must appear in parser outputs, runtime snapshots, and parity reports
- each snapshot must identify the evaluated closed-bar timestamp in both UTC and `America/New_York`
- parity closure is evaluated on the contract surface only, not on built-in helper convenience paths

## Required Artifact Integrity Fields

Every reusable parity or identity artifact must carry at least:

- `artifact_id`
- `artifact_role`
- `path_or_ref`
- `sha256`
- `created_on`
- `produced_by_stage`
- `required_contract_versions`
- `required_artifact_hashes`

## Close Conditions

`parity_closure` is closed only when:

- Python snapshot and MT5 snapshot share the same identity fields
- ordered feature vectors match within the agreed tolerance
- session features and external-alignment timestamps match within the agreed tolerance
- the negative fixture proves fail-fast or non-ready behavior instead of silent substitution

`artifact_identity_closure` is closed only when:

- dataset, bundle, runtime, and report identities are machine-readable
- required hashes are recorded and internally consistent
- runtime self-check can prove that the loaded artifact set matches the declared contract surface

## Operational Meaning

- no artifact may be treated as foundation evidence until both parity identity and artifact identity are machine-readable
- parity evidence is separate from promotion evidence
- artifact identity closure comes before exploration-only mode
