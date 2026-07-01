# Axiom Rift Base Contract

schema: axiom_rift_base_contract_doc_v1
status: draft_active
encoding: ascii_only
audience: codex_only

## Purpose

Define the base operating boundary for Project Axiom Rift before any label, feature set,
model family, trade logic, runtime authority, or live-readiness claim is frozen.

## Active Truth

- agent_rules: AGENTS.md
- reentry: registries/reentry.yaml
- claim_state: registries/claim_state.yaml
- contracts: contracts/
- configs: configs/
- registries: registries/
- campaigns: campaigns/
- source_package: src/axiom_rift/

Archive files are reference-only and are not active truth.

## Market Surface

- broker: FPMarkets
- symbol: US100
- timeframe: M5
- base_frame: US100 closed M5 bars
- external_alignment: own closed M5 series merged to US100 close timestamp
- leakage_policy: no_future_leakage

## Discovery Scope

Discovery is autonomous until explicit freeze.

The following are exploration variables:

- label shape
- label horizon
- feature family
- feature count
- feature order
- external inputs
- model family
- model count
- ensemble structure
- long-specific models
- short-specific models
- exit-specific models
- filters
- objectives
- thresholds
- trade logic
- position logic

Feature count is not constrained by this contract. A candidate may use one feature, many
features, or generated feature families if evidence supports reuse.

Model structure is not constrained by this contract. A candidate may use one model, multiple
models, ensembles, direction-specific models, exit models, filters, or other reproducible
decision surfaces if evidence supports reuse.

## Hard Rules

- Use closed M5 bars for signal decisions unless a later active runtime contract says otherwise.
- Do not use future data in labels, features, filters, calibration, sizing, or trade decisions.
- Keep every reusable candidate reproducible by recording inputs, code path, parameters, and
  artifact identity.
- Record durable artifact identity as repo-relative paths plus hashes.
- Use rolling-window evidence before promotion or freeze.
- Treat score samples, proxy samples, diagnostic samples, compile-only checks, and preview rows
  as non-authoritative.

## Freeze Requirements

A candidate cannot be frozen or promoted without:

- active contract or decision record
- dataset identity
- split boundaries
- feature/order hash when applicable
- artifact identity and hash when applicable
- recorded evaluation evidence
- explicit claim boundary update

## Claim Boundary

Current state:

- label_selected: false
- feature_set_selected: false
- model_selected: false
- runtime_probe_completed: false
- economics_pass: false
- materialization_ready: false
- runtime_authority: false
- live_ready: false

Forbidden without completed evidence:

- winner claim
- selected baseline claim
- production readiness claim
- runtime authority claim
- live-readiness claim
- inherited archive authority claim

## Campaign Rule

Campaigns must keep exploration outputs inside the campaign layout:

- campaigns/<campaign_id>/campaign.yaml
- campaigns/<campaign_id>/inputs.yaml
- campaigns/<campaign_id>/runs/<run_id>/
- campaigns/<campaign_id>/selected.yaml

Raw data must not be placed in campaign folders.

## Next Contract Work

- define first autonomous discovery campaign manifest
- define candidate identity format
- define evaluation and promotion evidence requirements
- define runtime evidence requirements before any runtime authority claim
