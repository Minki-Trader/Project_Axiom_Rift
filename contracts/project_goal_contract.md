# Axiom Rift Project Goal Contract

schema: axiom_rift_project_goal_contract_v1
status: draft_active
encoding: ascii_only
audience: codex_only

## Purpose

Define the top-level mission, target outcome, project boundary, and coordination model for
Project Axiom Rift.

This contract is the root objective for downstream contracts, research methods, Codex skills,
policies, campaigns, runs, and handoff work.

## Mission

Project Axiom Rift exists to autonomously discover, evaluate, materialize, and pre-live validate
a US100 M5 trading system by allowing Codex to explore labels, features, models, and trade logic.

The project should pursue frequent entry opportunities, controlled monthly drawdown, and strong
profitability after realistic trading costs.

## Target Outcome

The target system should aim to:

- generate approximately 5 to 10 entry events per active trading day
- maintain controlled monthly drawdown
- preserve strong profitability after realistic trading costs
- become materialized as EA and ONNX-ready artifacts before handoff

Exact evaluation gates, sizing rules, drawdown thresholds, profit factor thresholds, promotion
rules, and runtime validation rules belong in lower-level contracts.

## Project Scope

In scope:

- autonomous research
- label exploration
- feature exploration
- model exploration
- trade logic exploration
- candidate evaluation
- reusable artifact generation
- ONNX artifact preparation
- MQL5 EA development
- MT5 Strategy Tester validation
- pre-live validation package
- handoff package for a separate live-operation project

Out of scope:

- live trading
- real account operation
- production VPS operation
- live monitoring
- capital deployment
- live promotion authority

## Pre-Live Boundary

Axiom Rift stops at pre-live validation and handoff.

Live operation must be opened as a separate project with its own contracts, risk policy, runtime
monitoring, operational authority, and live-readiness claims.

EA or ONNX materialization inside this project is not a live-readiness claim.

## Coordination Model

User input may be informal, incomplete, or out of order.

Codex is responsible for:

- preserving user intent
- separating goals, contracts, policies, skills, campaigns, and implementation work
- proposing small contract increments before broad policy or skill work
- keeping active project files concise, machine-oriented, and ASCII-only
- keeping human-friendly explanations in chat
- avoiding premature freeze of labels, features, models, trade logic, runtime authority, or
  live-readiness claims

Codex must not edit project files unless the user explicitly asks to apply, implement, write,
create, patch, or push.

## Claim Boundary

This contract does not claim:

- label_selected: true
- feature_set_selected: true
- model_selected: true
- runtime_probe_completed: true
- economics_pass: true
- materialization_ready: true
- runtime_authority: true
- live_ready: true

This contract is an objective and boundary contract, not evidence of candidate performance.

## Downstream Contracts

This project goal should be refined through separate lower-level contracts:

- base_operating_contract
- discovery_freedom_contract
- feature_data_contract
- experiment_constants_contract
- evaluation_contract
- kpi_ledger_contract
- candidate_identity_contract
- promotion_contract
- materialization_contract
- runtime_validation_contract
- handoff_contract
- codex_skill_policy

Downstream contracts must preserve this project boundary unless a later explicit decision record
changes the project scope.
