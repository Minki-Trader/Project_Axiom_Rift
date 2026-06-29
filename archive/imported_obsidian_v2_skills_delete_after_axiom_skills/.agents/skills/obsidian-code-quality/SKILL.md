---
name: obsidian-code-quality
description: Raise implementation quality so code reads like a well-structured expert answer, not just a script that happens to run. Use when writing or reviewing Python, MQL5, feature, label, split, model, dataset, parity, report, or test code.
---

# Obsidian Code Quality

Use this skill when implementation quality matters, especially for quant research code.

This is different from `obsidian-code-surface-guard`. Code surface decides where code belongs. Code quality decides whether the implementation itself is clear, disciplined, and trustworthy.

## Automatic Bundle

Trigger automatically after `obsidian-code-surface-guard` for non-trivial code edit(비사소 코드 변경) in Python(파이썬), MQL5, feature(피처), label(라벨), split(분할), model(모델), dataset(데이터셋), parity(동등성), report(보고서), or test(테스트) code.

Effect(효과): code quality(코드 품질), responsibility(책임), flow(흐름), contract(계약), and test intent(검증 의도)를 구현 중에 점검해서 실행만 되는 큰 스크립트로 흐르지 않게 한다.

## Quality Standard

Code should read like a good expert answer:

- the responsibility is clear
- the reasoning flow is visible
- inputs, processing, and outputs are separated
- assumptions are near the code that depends on them
- names explain intent
- constants and thresholds are not hidden magic
- failures explain what broke
- outputs can be traced later
- tests protect the intended behavior, not only execution

## Quant-Specific Quality Points

For trading or research code, treat these as core quality issues:

- input data identity and expected columns
- timestamp meaning and timezone policy
- feature calculation boundary
- label calculation boundary
- train, validation, and OOS split boundary
- lookahead or future-data leakage risk
- dataset id, config, row count, hash, and artifact path traceability
- whether tests check financial or temporal meaning, not only that code runs

## Required Output Before Or During Implementation

- `responsibility`: what this code owns
- `flow`: how data moves from input to output
- `contracts`: input, output, and failure contracts
- `assumptions`: assumptions that must not be hidden
- `traceability`: ids, hashes, configs, row counts, or artifact paths to preserve
- `test_intent`: what the tests prove
- `quality_risk`: the most likely way this code could become misleading or hard to change

## Do Not

- Do not write a large script where parsing, feature work, labels, model training, and reporting are tangled together.
- Do not let a passing test replace a clear contract.
- Do not hide a business or trading assumption in a variable name like `threshold = 0.5`.
- Do not mix feature and label logic unless the boundary is explicit and tested.
- Do not rely on timestamp meaning by memory; use the project time-axis policy or name the unresolved assumption.
