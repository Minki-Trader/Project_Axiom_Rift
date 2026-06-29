---
name: obsidian-reference-scout
description: Find and use external references for correct API usage, syntax, implementation patterns, MQL5/MT5 EA behavior, Strategy Tester behavior, library behavior, quant methods, and idea scouting. Use when project memory is not enough, an API may be version-sensitive, EA run-variant management touches official behavior, or alpha/research ideas need external examples.
---

# Obsidian Reference Scout

Use this skill when outside references can improve correctness, idea quality, or confidence in environment behavior.

This skill is for scouting and grounding, not copying.

## Automatic Code-Writing Pair

For every code-writing packet(code-writing packet, 코드 작성 묶음), run this scout beside `obsidian-code-surface-guard(코드 표면 가드)`.

Use external lookup(외부 확인) when the code touches MQL5/MT5(MetaTrader 5, 메타트레이더5), MetaEditor(메타에디터), strategy tester(전략 테스터), file handoff(파일 인계), external API(외부 API), CLI, or library behavior(라이브러리 동작) such as pandas/sklearn/numpy/LightGBM.

If the code is pure internal logic(순수 내부 로직) with no uncertain API(API 사용법), syntax(구문), version-sensitive behavior(버전 민감 동작), or external pattern(외부 패턴), record `reference_scout: not_required(레퍼런스 탐색 불필요)` with the reason(reason, 이유). This record belongs in the implementation precheck or completion report; do not leave it implicit.

Effect(effect, 효과): implementation(구현)을 프로젝트 기억(project memory, 프로젝트 기억)만으로 단정하지 않고, 필요한 곳에서는 official docs(공식 문서)나 maintained source(유지보수되는 원천)로 접지한다.

## When To Use

- correct function, API, or syntax usage is uncertain
- library behavior may depend on version
- MQL5 or MT5 tester behavior is unclear
- EA(`Expert Advisor`, 전문가 자문) management touches `#include(포함)`, `input/sinput(입력/고정 입력)`, `OnInit/OnTick/OnTester(초기화/틱/테스터)`, `.set` files(설정 파일), tester properties(테스터 속성), or optimization frames(최적화 프레임)
- LightGBM, pandas, sklearn, numpy, or another library usage needs confirmation
- implementation patterns from maintained GitHub projects may help
- dependency, packaging, clean checkout, or CI behavior may differ by environment
- quant method choice, validation frame, backtest method, or runtime parity needs grounding
- alpha exploration is stuck and outside examples may suggest new ideas
- forum posts may reveal practical edge cases

## Source Priority

1. Official documentation or vendor docs.
2. Maintained source repository, examples, release notes, or issue discussions.
3. Well-scoped GitHub examples with readable code and recent maintenance.
4. Forum or community posts, including MQL5 forum, only as idea candidates or practical warnings.

## Required Output

- `question`: what usage, idea, or pattern was researched
- `sources_checked`: which sources were checked
- `source_quality`: official, maintained code, example, issue, forum, or weak
- `found_pattern`: the useful pattern or warning
- `project_fit`: how it fits or conflicts with this repo's contracts
- `do_not_copy`: what should not be copied directly
- `recommended_use`: adopt, adapt, treat as idea, or reject
- `not_required_reason`: only when no lookup was needed

## EA Reference Hard Trigger(EA 레퍼런스 강제 트리거)

For MT5 EA(`Expert Advisor`, 전문가 자문) architecture, run variant management(실행 변형 관리), Strategy Tester(전략 테스터), `.set` file(설정 파일), `input/sinput(입력/고정 입력)`, `#include(포함)`, `#property(프로그램 속성)`, or `OnInit/OnTick/OnTester(초기화/틱/테스터)` behavior, check official MQL5 documentation first.

Minimum source questions(최소 확인 질문):

- Is this behavior defined in official docs(공식 문서)?
- Does it belong in main `.mq5` entrypoint(진입점) or `.mqh` include module(포함 모듈)?
- Is the run difference parameter-only(파라미터만) or code-changing(코드 변경)?
- Which identity fields(정체성 필드) must be recorded so tester output(테스터 출력) can be traced?

Effect(효과): EA 관리 판단을 기억이나 forum habit(포럼 관습)에 맡기지 않고, official behavior(공식 동작)와 project contract(프로젝트 계약)를 같이 맞춘다.

## Guardrails

- Prefer official docs for API and syntax questions.
- Do not copy external code wholesale into this repo.
- Do not trust forum performance claims as evidence.
- Do not let external examples override project contracts for time axis, dataset identity, split policy, artifact identity, or runtime authority.
- If a source is old, version-specific, or unclear, say so.
- If browsing or source lookup was not performed, do not present the answer as externally verified.

## Example

If MQL5 file handoff behavior is unclear, scout official MQL5 docs first, then relevant forum or GitHub examples. The useful result might be a pattern such as waiting for file size stability, but the implementation still needs to fit this project's runtime parity and artifact identity rules.
