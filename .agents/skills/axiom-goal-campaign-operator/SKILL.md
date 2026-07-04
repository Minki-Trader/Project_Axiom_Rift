---
name: axiom-goal-campaign-operator
description: Use this Project Axiom Rift skill when a user gives a short /goal, asks to automate or operate toward the top-level US100 M5 trading-system goal, chooses, opens, or closes C campaigns or R runs, reviews next work after a closeout, asks whether to keep digging, or needs drift-resistant campaign/run operation with failure-as-asset and mandatory MT5 evidence guardrails.
---

# Axiom Goal Campaign Operator

## Purpose

Operate Project Axiom Rift from a short goal prompt without losing the top-level target, skipping evidence, inventing claims, or turning failures into missing data.

## Required Context

Before acting, read:

1. `AGENTS.md`
2. `registries/reentry.yaml`
3. `registries/claim_state.yaml`
4. `contracts/project_goal_contract.md`
5. `contracts/evaluation_contract.md`
6. `contracts/goal_operation_policy.yaml`
7. Active campaign manifest when one exists or campaign work is requested.
8. `.agents/skills/axiom-mt5-validation-guardrails/SKILL.md` before any numbered run or MT5 evidence work.
9. `python -m axiom_rift.cli validate-repo-state` output before next-work, campaign/run, or closeout decisions.

Read `references/operating_flow.md` before opening or closing a campaign, opening or closing a run, processing `/goal`, or deciding whether to keep digging.
When data surfaces are touched, refresh in order: `build-us100-base-frame`, `derive-us100-clean-periods`, then `build-us100-rolling-windows`.

## Top-Level Target

Preserve this target unless a later active contract changes it:

- FPMarkets US100 M5.
- Approximately 5 to 10 entry events per active trading day.
- Controlled monthly drawdown; exact threshold not frozen.
- Strong profit factor after realistic spread and slippage; exact threshold not frozen.
- EA and ONNX-ready pre-live handoff package.
- Live operation is out of scope.
- Labels, features, model families, objectives, and trade shapes remain unrestricted exploration variables until explicit evidence-based freeze.
- Early discovery uses fixed-lot evaluation; equity-percent sizing is deferred to later robustness or growth validation after candidate quality is established.

## Operating Rules

- Expand short goals into bounded work-unit actions.
- Decide the operation class first: new campaign, new run, repair, closeout, synthesis due check, or pause.
- Check repo state before deciding next work; separate pre-existing blockers from current-task regressions.
- Open a run only for a true variant; do not treat threshold, window, SL/TP, or session nudges as a new run unless they ask a distinct campaign question.
- For every opened run, complete proxy, MT5 logic parity, proxy-vs-MT5 parity, MT5 tick, execution divergence, fold-isolated tick, fold-isolated divergence, and closeout.
- Treat aggregate MT5 KPI as diagnostic only.
- Failures are assets: record negative memory, parity lesson, execution divergence lesson, evidence gap, or non-portable lesson.
- Broken code is not a failure asset and not hypothesis evidence.
- Never record "the code did not work" as completed work and stop; triage, repair in scope, rerun, then record evidence.
- If code cannot be repaired in the current turn, record a blocker with root cause, reproduction command, failing artifact path, next concrete repair step, and required user or external state.
- Do not skip MT5 because proxy is weak.
- Do not create selected, economics_pass, runtime, ONNX, promotion, or live claims without active contracts and completed evidence.
- Keep project files ASCII and machine-oriented; explain in Korean only in chat.

## Closeout Discipline

- Close a run only from fold-isolated evidence or a complete exception.
- Do not close a run, campaign, or goal from broken code, parser failure, compile failure, runner failure, or KPI missing because code failed.
- After every run closeout, validate changed surfaces, reflect closeout-scoped changes on local `main`, and push `main` to `origin`.
- Do not report a run closeout as operationally complete if the closeout changes were not pushed to `origin/main`.
- Preserve unrelated dirty work; do not force-push, hard reset, or stage unrelated files to satisfy closeout git sync.
- Close a campaign only when no meaningful variant remains inside its boundary, remaining work is adjacent tuning, all relevant runs have evidence closeout, and synthesis due check is recorded.
- If there is no active campaign after closeout, next work is choosing a new major C campaign hypothesis or waiting for synthesis readiness.

## Validation

Run the strongest relevant subset:

- `python -m axiom_rift.cli validate-work-unit <campaign_or_synthesis_path>` when a work unit changed.
- `python -m axiom_rift.cli validate-repo-state` before next-work, campaign/run, or closeout decisions; report pre-existing blockers separately.
- `python -m axiom_rift.cli build-us100-base-frame`, then `python -m axiom_rift.cli derive-us100-clean-periods`, then `python -m axiom_rift.cli build-us100-rolling-windows` when data baseline surfaces changed.
- `python -m axiom_rift.cli validate-templates` when templates/contracts changed.
- `python -m unittest discover -s tests` when code, validators, CLI, or policy tests changed.
- `python -m compileall -q src tests` when Python changed.
- Skill quick validation when this skill changed.
- ASCII scan and `git diff --check`.
