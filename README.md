# Project Axiom Rift

schema: axiom_rift_readme_v2
audience: codex_only
encoding: ascii_only

## Pointers

- agent rules: `AGENTS.md`
- decision cursor: `registries/decision_cursor.yaml`
- boot summary: `registries/reentry.yaml`
- claim state: `registries/claim_state.yaml`
- active contracts: `contracts/`
- active config: `configs/`
- source package: `src/axiom_rift/`
- campaigns: `campaigns/`
- legacy archive: `archive/`

## Operating Model

This repository uses developer-style campaign manifests instead of narrative stages.

- `campaigns/`: reproducible research campaigns and top-level synthesis work units
- `src/axiom_rift/`: reusable code
- `contracts/`: active interfaces and claim rules
- `configs/`: environment, market, and runtime settings
- `registries/`: state, decisions, runs, and artifacts
- `artifacts/`: reusable generated outputs, ignored by default except README files

## Claim Boundary

At restart, no label, feature set, model, runtime authority, operating promotion, or live-readiness
claim is inherited from archived Obsidian Prime v2 material.

Use `registries/claim_state.yaml` as the current truth.
