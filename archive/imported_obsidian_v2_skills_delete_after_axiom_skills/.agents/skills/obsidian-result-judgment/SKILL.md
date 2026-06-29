---
name: obsidian-result-judgment
description: Judge project results with the correct boundary before claiming positive, negative, invalid, blocked, promotion candidate, operating promotion, runtime probe, or runtime authority.
---

# Obsidian Result Judgment

Use this skill when a result, run, experiment, model, package, backtest, PR, or stage outcome is interpreted for the user or written into a register.

## Must Read

- `docs/policies/result_judgment_policy.md`
- `docs/policies/promotion_policy.md`
- `docs/policies/run_result_management.md` when run status changes
- `docs/policies/kpi_measurement_standard.md` when KPI is involved

## Required Output

- `result_subject`: what is being judged
- `evidence_available`: KPI, report, artifact, registry row, test, backtest, or runtime output
- `evidence_missing`: what is absent or weak
- `judgment_label`: positive, negative, invalid, inconclusive, blocked, exploratory, promotion_candidate, operating_promotion, runtime_probe, runtime_authority, or not_applicable
- `claim_boundary`: what can be said now and what cannot
- `next_condition`: smallest condition that could strengthen, weaken, or close the judgment
- `user_explanation_hook`: plain-language meaning for `obsidian-answer-clarity`
- `runtime_learning_probe_decision`: whether weak proxy/candidate-gate failure(약한 프록시/후보 게이트 실패) still required MT5 action(엠티5 행동), repair_attempt(수리 시도), or blocked/inconclusive(차단/불충분) boundary

## Guardrails

- Do not call a result positive only because a script ran.
- Do not call a result negative when the run is invalid or missing evidence.
- Do not turn promotion_candidate into operating_promotion.
- Do not turn runtime_probe into runtime_authority.
- Do not label a packet negative/complete(부정/완료) when MT5 was skipped only because proxy_bad/candidate_gate_failed/not_strong_candidate/low_trade_count_expected/long_short_imbalanced/cost_expensive(프록시 부진/후보 게이트 실패/강한 후보 아님/거래 수 부족 예상/롱숏 비대칭/비용). The judgment must be blocked/inconclusive(차단/불충분) unless runtime_learning_probe_decision_gate(런타임 학습 탐침 결정 게이트) records a valid run_probe/run_after_repair/not-run-after-repair decision(탐침 실행/수리 후 탐침 실행/수리 후 미실행 결정).
- On Windows deep stage/MT5 artifact paths, do not label evidence `missing`, a setup `invalid`, or a result `blocked` from one native path failure. First discover with repo-relative `rg --files`/`rg`; when file content or existence is needed, use `foundation.control_plane.ledger.io_path`, `path_exists`, or a helper built on them from the first read, not as a late retry after `Path.read_text`, `Path.exists`, PowerShell `Get-Content`, `Import-Csv`, or pandas direct paths. If the long-path-safe read also fails, record that outcome before applying the judgment label.
- Pair final user-facing judgment with `obsidian-claim-discipline` and `obsidian-answer-clarity`.
