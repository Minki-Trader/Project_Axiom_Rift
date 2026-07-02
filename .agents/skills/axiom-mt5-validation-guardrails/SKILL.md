---
name: axiom-mt5-validation-guardrails
description: Use this Project Axiom Rift skill whenever work touches MT5 EAs, MQH include modules, MQL5 scripts, tester configs, MT5 KPI parsers, proxy-vs-MT5 parity, execution-divergence evidence, or campaign run evidence generated from MT5. Enforces mandatory MT5 validation for opened runs, no proxy-only scout cuts, closed-bar logic parity, tick-mode execution KPI management, reusable source placement, and thin-EA/MQH-first design.
---

# Axiom MT5 Validation Guardrails

## Purpose

Enforce Project Axiom Rift MT5 workflow rules:

- Use closed-bar MT5 runs to prove proxy and EA logic parity.
- Use tick-mode MT5 runs for actual execution and KPI management.
- Treat proxy output as a reference surface, not as a screening gate that can skip MT5.
- Keep reusable EA, MQH, script, runner, and parser components in stable project paths.
- Keep EA bodies thin and move reusable logic into MQH/Python helpers.

## Non-Negotiable Rules

1. Do not run proxy-only scouts for opened runs.
2. Do not skip, cancel, or close MT5 validation because proxy KPI is weak, ugly, or obviously losing.
3. Do not describe proxy as a go/no-go gate for MT5.
4. Do not treat tick-mode proxy mismatch as automatic logic failure.
5. Do not treat closed-bar parity PnL as execution economics.
6. Do not judge a run closeout from compile success alone.
7. Do not rewrite shared or reusable EA, parser, runner, MQH, or helper components from scratch when a project source already exists.
8. Do not put raw data or run artifacts in campaign roots.
9. Do not create runtime, live, selected, promotion, or ONNX claims from MT5 probes.

## Mandatory Run Sequence

When a numbered run is opened, carry it through this sequence unless the user explicitly stops work:

1. Proxy evidence and KPI record.
2. MT5 closed-bar logic parity run and KPI record.
3. Proxy-vs-MT5 logic parity record.
4. MT5 tick execution KPI run and KPI record.
5. Closed-bar-vs-tick execution divergence record.
6. Rolling-window fold-isolated MT5 tick KPI and fold-isolated execution divergence before closeout.
7. KPI missing-value check and work-unit validation.

Proxy results may guide diagnosis, parity expectations, and repair notes. They must not decide whether MT5 is attempted.

## Required MT5 Evidence Split

Every campaign run that uses MT5 must separate these surfaces:

- `logic_parity`: closed-bar OHLC mode. Purpose is proxy-vs-EA logic parity.
- `execution_kpi`: tick mode. Purpose is real MT5 execution economics and robustness.
- `execution_divergence`: comparison between closed-bar logic behavior and tick behavior.

Required interpretation:

- Closed-bar parity passed means the proxy and EA implement the same intended logic.
- Tick KPI is the primary economics surface.
- Tick divergence is evidence to analyze, not something to hide by forcing proxy parity.
- Aggregate full-period MT5 KPI is diagnostic only for closeout.
- Run closeout judgment must use rolling-window fold-isolated MT5 tick evidence, unless a fold-isolated exception is recorded with reason.

## Required KPI Files

For new or repaired runs, prefer explicit KPI families:

- `kpi/proxy.json`
- `kpi/mt5_logic_parity.json`
- `kpi/mt5_tick.json`
- `kpi/proxy_vs_mt5_logic_parity.json`
- `kpi/execution_divergence.json`
- `kpi/mt5_tick_by_fold.json` when preparing run closeout
- `kpi/execution_divergence_by_fold.json` when preparing run closeout

Do not create or rely on generic `kpi/mt5.json` or `kpi/proxy_vs_mt5.json` files.

Every parser must check missing required KPI values. Missing fields must be either populated or recorded with `applies: false` or `deferred_with_reason`.

## Parity Rules

Closed-bar parity must check:

- entry count
- entry timestamp
- entry direction
- exit count
- exit timestamp
- exit reason
- position lifecycle

Tick-mode execution comparison must check:

- tick trade count
- tick net PnL
- tick max drawdown
- tick profit factor
- tick win rate
- tick expectancy
- divergence in exit time/reason versus closed-bar logic
- spread/slippage or broker execution fields when available

Do not require tick exit events to match proxy exits one-to-one unless the strategy explicitly runs on tick-level logic.

## Rolling-Window Closeout Gate

Project Axiom Rift uses the active rolling-window split policy for run judgment.

Before run closeout:

- Read `registries/rolling_windows.yaml` and the run campaign inputs.
- Treat one full-period MT5 tick run as baseline diagnostic evidence only.
- Do not close a run from aggregate MT5 KPI alone.
- Produce or require fold-isolated MT5 tick KPI for each active test OOS fold.
- Produce or require fold-isolated execution divergence for each active test OOS fold.
- If fold-isolated MT5 execution is impossible, record `gate_report.rolling_window_closeout_gate.fold_isolated_exception` with `applies`, `reason`, `blocking_condition`, and `revisit_when`.

Expected closeout files:

- `kpi/mt5_tick_by_fold.json`
- `kpi/execution_divergence_by_fold.json`

The validator must block closeout decisions when these files or a complete exception are missing.

## Source Placement

Keep reusable source in these paths:

- EA sources: `src/axiom_rift/mt5/experts/`
- MQH include modules: `src/axiom_rift/mt5/include/`
- MQL5 scripts: `src/axiom_rift/mt5/scripts/`
- Python MT5 runners, compilers, parsers: `src/axiom_rift/mt5/`
- Proxy engines: `src/axiom_rift/proxies/`
- Tests: `tests/`
- Durable run KPI evidence: `campaigns/<campaign_id>/runs/<run_id>/kpi/`

Do not create ad hoc top-level script, scratch, experiment, or stage folders.

## Reuse Before Rewrite

Before editing or creating MT5 code:

1. Search existing source paths with `rg --files`.
2. Read the existing EA, MQH, runner, and parser files that touch the requested surface.
3. Patch existing shared code with `apply_patch` unless a new named reusable module is truly required.
4. Record durable artifact identity as repo-relative paths plus hashes.

Do not regenerate reusable EA plumbing or KPI parser code from memory when the project already has it.

Run-specific exception:

- New run-specific EA bodies are allowed when a run needs a distinct wrapper, input surface, or orchestration.
- Variant-specific signal logic is allowed when it represents a new hypothesis or run surface.
- New code must still reuse existing shared compile, runner, parser, CSV, parity, symbol-spec, sizing, and ledger helpers.
- If a run-specific component becomes useful across runs, promote it into `src/axiom_rift/mt5/include/` or a Python helper instead of copying it.

## Thin EA Policy

Keep EA bodies thin:

- Entry point, inputs, trade calls, and simple orchestration may stay in the EA.
- Reusable KPI writing, CSV helpers, parity helpers, signal-state logic, sizing, and symbol-spec helpers should move to MQH or Python helpers when reused.
- Prefer MQH modules for repeated MQL logic and Python modules for parsing, hashing, validation, and ledger writing.

When adding MQH:

- Place it under `src/axiom_rift/mt5/include/`.
- Copy it to the terminal include path from a Python runner when compiling.
- Keep includes project-owned and ASCII-only.

## Validation Workflow

For MT5 EA or parser work, run the strongest feasible subset:

1. Python import/tests: `python -m unittest discover -s tests`
2. Python bytecode: `python -m compileall -q src tests`
3. EA compile through project CLI or MetaEditor helper
4. MT5 tester run for the touched mode
5. KPI parse
6. Missing KPI check
7. Proxy-vs-MT5 logic parity or execution divergence record
8. `validate-work-unit` for the active campaign
9. `validate-templates`
10. ASCII scan and `git diff --check`

Never stop at compile success when the user asked for MT5 validation.
