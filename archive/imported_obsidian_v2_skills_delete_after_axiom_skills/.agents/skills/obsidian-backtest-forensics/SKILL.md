---
name: obsidian-backtest-forensics
description: Inspect backtest and Strategy Tester evidence, settings, spread, commission, slippage, trade list, deposits, leverage, modeling mode, and report paths before tester results are trusted.
---

# Obsidian Backtest Forensics

Use this skill when work creates, reads, compares, packages, or reports MT5 Strategy Tester, broker terminal, or backtest outputs.

## Required Output

- `tester_identity`: terminal, broker, symbol, timeframe, deposit, leverage, modeling mode, spread, commission, and date range
- `ea_identity`: EA entrypoint, include module hashes, `.set` file, parameter hash, and model or bundle hash
- `report_identity`: report path, snapshot path, terminal output path, and hash when available
- `trade_evidence`: trade count, gross/net result, drawdown, profit factor, and trade list availability
- `cost_assumptions`: spread, commission, slippage, swap, and missing costs
- `forensic_checks`: checks performed against settings drift, missing output, or malformed report
- `mt5_runtime_probe_contract`: standard/exception profile(표준/예외 프로필), validation_is/oos period(검증 내부/표본외 기간), `/portable` execution(포터블 실행), required report coverage(필수 보고서 커버리지), claim effect(주장 효과)
- `runtime_learning_probe_decision`: MT5 action(엠티5 행동), not-run reason(미실행 사유), repair attempts(수리 시도), environment/materialization blocker(환경/물질화 차단), and claim effect(주장 효과)
- `backtest_judgment`: usable, usable_with_boundary, inconclusive, invalid, or blocked

## Guardrails

- Do not trust a report if tester identity is unknown.
- Do not compare tester runs with different cost or modeling assumptions as if they are equal.
- Do not call a backtest reviewed when the output path or run identity is missing.
- Do not use tester profit alone as a promotion argument.
- Do not accept proxy_bad/candidate_gate_failed/not_strong_candidate/low_trade_count_expected/long_short_imbalanced/cost_expensive(프록시 부진/후보 게이트 실패/강한 후보 아님/거래 수 부족 예상/롱숏 비대칭/비용)를 MT5 Strategy Tester not-run reason(전략 테스터 미실행 사유)으로 판정하지 않는다. If no_actionable_runtime_surface(실행 가능한 런타임 표면 없음) is the blocker, require repair_attempt(수리 시도) evidence before blocked/inconclusive(차단/불충분).
- Standard runtime_probe(표준 런타임 탐침)는 validation_is(검증 내부) `2025.01.02 -> 2025.10.01`과 oos(표본외) `2025.10.01 -> 2026.06.18` 쌍, `/portable(포터블 모드)`, completed Strategy Tester report(완료 전략 테스터 보고서)를 요구한다.
- report output missing(보고서 출력 누락)이면 terminal mode/path/report generation(터미널 모드/경로/보고서 생성)을 먼저 점검한다. Missing report(누락 보고서)는 runtime_probe_completed(런타임 탐침 완료) 근거가 아니다.
