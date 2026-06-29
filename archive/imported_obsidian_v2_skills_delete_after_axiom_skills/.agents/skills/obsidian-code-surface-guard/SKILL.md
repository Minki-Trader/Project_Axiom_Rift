---
name: obsidian-code-surface-guard
description: Prevent Project Obsidian Prime v2 code-surface drift, monolith growth, and EA run-variant sprawl. Use when adding, moving, or modifying code in foundation, pipelines, MT5 EA files, .mqh modules, .set/tester configuration, stage scripts, model builders, feature calculators, runtime helpers, or report materialization paths.
---

# Obsidian Code Surface Guard

Use this skill for code changes before choosing files or writing implementation.

## Automatic Code-Writing Gate

For every code-writing packet(code-writing packet, 코드 작성 묶음), including Python(파이썬), MQL5, tests(테스트), stage scripts(단계 스크립트), pipelines(파이프라인), model builders(모델 빌더), runtime helpers(런타임 도구), and report materializers(보고서 물질화 도구), run this guard before editing files.

Pair it with `obsidian-reference-scout(레퍼런스 탐색)` in the same precheck. The effect(effect, 효과) is that placement(배치) and external correctness(외부 정확성)을 분리해서 확인한다.

If no file is edited, mark `code_surface_guard: not_required(코드 표면 가드 불필요)` with a short reason(reason, 이유).

## Must Read

- `docs/policies/architecture_invariants.md`
- `docs/registers/architecture_debt_register.md`
- the touched module, caller, and nearest existing orchestration path

## Required Output

- `owner_module`: where reusable logic belongs
- `caller`: which pipeline, stage script, EA, or test calls it
- `input_contract`: input data shape, feature surface, or config boundary
- `output_contract`: output artifact, report, or runtime effect
- `artifact_or_report_relation`: what durable artifact or report is affected
- `monolith_risk`: whether the change concentrates too much logic in one file
- `placement_decision`: why the chosen location is correct
- `reference_scout_pairing`: whether `obsidian-reference-scout(레퍼런스 탐색)` was used, or why it was not required

## Placement Rules

- Put reusable feature/model/runtime logic under the correct `foundation` owner.
- Use `foundation/pipelines` for orchestration, not as the long-term owner of reusable feature logic.
- Use stage scripts for materialization and stage-local analysis, not reusable contracts.
- Use MT5 EA code for execution and verification, not as the only owner of feature or model semantics.
- Do not add another broad all-in-one EA or pipeline file when a smaller owner module can hold the logic.

## EA Run Variant Hard Trigger(EA 실행 변형 강제 트리거)

Trigger automatically when work touches MT5 EA(`Expert Advisor`, 전문가 자문), `.mq5`, `.mqh`, `.set`, Strategy Tester(전략 테스터), optimization pass(최적화 회차), runtime package(런타임 패키지), model bundle(모델 번들), tester property(테스터 속성), EA run config(EA 실행 설정), or Tier A primary + Tier B fallback routing(Tier A 우선 + Tier B 대체 라우팅).

Before editing, classify the run-specific difference(실행별 차이):

- `parameter_only(파라미터만)`: keep the EA entrypoint(진입점) and modules(모듈) unchanged; create or update `.set`, `run_manifest.json`, and KPI record(KPI 기록).
- `module_change(모듈 변경)`: update the smallest `.mqh` owner module(소유 모듈), version it, and record module sha256(모듈 해시).
- `entrypoint_change(진입점 변경)`: only when lifecycle(생명주기), `#property(프로그램 속성)`, file handoff(파일 인계), or tester wiring(테스터 연결)이 바뀐다.
- `new_runner_required(새 실행기 필요)`: only when existing runner(실행기) + modules(모듈) cannot represent the experiment.

Default no(기본 금지): do not manage run variants by copying a new broad `.mq5` file for each run.

Required output addition(필수 출력 추가):

- `ea_variant_boundary`: one of the four classes above
- `entrypoint_identity`: `.mq5` path and whether it changed
- `set_identity`: `.set` or config path and hash when applicable
- `module_identity`: touched `.mqh` modules and hashes
- `tester_identity`: tester model(테스터 모델), deposit(예치금), leverage(레버리지), symbol/timeframe(심볼/시간프레임)

Effect(효과): run01A/run01B-style variants(실행 변형)가 code sprawl(코드 난립)로 숨지 않고, configuration(설정), module version(모듈 버전), and evidence identity(근거 정체성)로 추적된다.

Routing note(라우팅 주의): Tier A primary + Tier B fallback routing(Tier A 우선 + Tier B 대체 라우팅)은 parameter-only(파라미터만)일 수도 있고 module_change(모듈 변경)일 수도 있다. combined record(합산 기록)는 actual routed total(실제 라우팅 전체)인지 synthetic sum(합성 합산)인지 코드와 장부에서 분명히 남긴다.

## Stop Conditions

- The caller is unknown.
- The effect of the code on artifacts, reports, or runtime behavior is unknown.
- The change deepens registered architecture debt without an explicit task packet or decision memo.
