---
name: obsidian-workflow-drift-guard
description: Prevent work from drifting away from the actual blocker by separating missing material, missing tools, missing environment, missing permission, and changed goals. Use when a task risks processing absent data, pretending an unavailable tool ran, or turning a tool-building task into unrelated validation.
---

# Obsidian Workflow Drift Guard

Use this skill when the work may drift from the original job into a nearby but different job.

## Automatic Bundle

Trigger automatically when source material(원재료), tool(도구), environment(환경), permission(권한), MT5 output(MT5 출력), external verification(외부 검증), or recovery(복구) is missing, broken, unavailable, or uncertain.

Effect(효과): blocker(차단 사유)를 source material(원재료), tool(도구), environment(환경), permission(권한), code(코드), or unclear goal(불명확한 목표)로 나누고, 가능한 recovery(복구)나 retry(재시도)를 먼저 시도한다.

## Simple Model

Think of making pottery:

- material: the clay or source data
- tool: the kiln, code path, library, MT5 terminal, or runner
- environment: the place where the tool can really run
- product: the artifact or answer we are trying to make

Do not process clay that does not exist. Do not pretend to fire pottery without a kiln. Do not spend the whole pass re-checking clay when the real blocker is that the kiln is missing.

## Required Check

Before changing direction, identify:

- `product`: what are we trying to produce?
- `material_state`: available, missing, partial, or unknown
- `tool_state`: available, missing, broken, or wrong environment
- `environment_state`: usable, unavailable, unverified, or not required
- `current_blocker`: material, tool, environment, permission, code, or unclear goal
- `next_action`: continue, fetch material, build tool, fix environment, lower claim, or ask user
- `drift_risk`: what nearby task could distract from the real blocker?

## Path/Name Resolution Preflight

Use this preflight when a file path(파일 경로) or packet filename(패킷 파일명) is inferred from convention(관례), memory(기억), user text without repo-relative confirmation(저장소 상대 경로 확인 없는 사용자 문구), or an artifact family with naming variance(이름 변형이 있는 산출물군) such as `docs/contracts/*`, `docs/agent_control/grok_reviews/*/`, or stage packet folders(단계 패킷 폴더).

Required behavior:

1. Discover first with repo-relative `rg --files` or targeted `rg -g` search(대상 검색). If the parent folder is known, list the smallest sufficient directory(최소 충분 디렉터리)를 먼저 본다.
2. For Windows glob(윈도우 글롭), prefer `rg pattern root -g "*.ext"` over wildcard directory assumptions(와일드카드 디렉터리 추정).
3. If the first open/read(열기/읽기) fails once, stop adjacent guessing(인접 추정 중단) and list the parent directory before trying another filename(파일명).
4. Adjacent guessing(인접 추정) means same parent directory(같은 상위 폴더) plus a tweaked basename(바꾼 파일명), same artifact role(같은 산출물 역할) plus a different extension(다른 확장자), or same stage/packet id(같은 단계/패킷 ID) plus a different suffix(다른 접미사).
5. When discovery corrects the path(경로를 바로잡음), record wrong assumption(잘못된 가정), repo-relative canonical path(저장소 상대 정식 경로), and discovery method(발견 방법) briefly.
6. If enumeration(목록화) still finds no file, classify it as `missing_material(자료 누락)` and do not substitute a nearby file(가까운 파일) as if it were equivalent.

Repo-scoped skills(저장소 전용 스킬) default to `.agents/skills/<skill-name>/SKILL.md`. External skill paths(외부 스킬 경로) are valid only when explicitly provided(명시적으로 제공됨) by the session skill roots(세션 스킬 루트) or the user.

Effect(효과): path hygiene(경로 위생) prevents repeated wrong-path retries(잘못된 경로 재시도) while preserving repo-relative artifact identity(저장소 상대 산출물 정체성). This preflight(사전확인) does not replace hash(해시), ledger(장부), MT5 evidence identity(MT5 근거 정체성), gates(게이트), thresholds(임계값), or runtime requirements(런타임 요구).

## Material Recovery Order

If required material is missing, do not stop at "design is still possible" when the requested product needs that material.

Use this order:

1. Check whether the material already exists inside the current repo or declared current-project data root.
2. Check whether a current repo tool can regenerate it.
3. Check whether the required source data exists inside the current project boundary.
4. If the material cannot be recovered inside the current project boundary, mark the task `blocked` or lower the claim.
5. Do not use legacy snapshots, external folders, old project outputs, forum files, or ad hoc internet artifacts unless the user explicitly asks.

External or legacy material is not a default fallback.

## Recovery Action Rule

Missing required material, tools, or environment is not a reason to abandon or quietly defer the original task.

Use this order:

1. If Codex can restore, regenerate, install, configure, fetch, create, patch, or run the required current-project material or tool within available permissions, do that first.
2. If the current tool is stale, wrong-surface, or missing, create or patch the narrow current-project tool before reporting `blocked`.
3. If an external runtime check is required, execute the narrowest real runtime check that can produce the requested artifact or failure log.
4. If user action is required, ask for the exact action and explain what work resumes after it is done.
5. After recovery, return to the original product instead of drifting into a new task.
6. Only mark the task blocked when neither Codex action nor a clear user action can complete the prerequisite in the current pass.

Example: if MT5 installation, broker login, terminal setup, or account connection is required, ask the user for that setup explicitly. Once available, resume the current project regeneration or verification path.

## Pre-Blocked Evidence Rule

Before writing `blocked`, produce at least one of these evidence types:

- `recovery_attempt`: the exact source material(원재료), tool(도구), or environment(환경) recovery tried in the current pass
- `created_or_patched_tool`: the current-project tool created or patched to remove the blocker
- `execution_attempt`: the command, terminal action, MT5 run, strategy tester run, or script invocation that tried to produce the requested output
- `failure_log`: the error, missing terminal state, permission failure, or unavailable environment that stopped the run
- `required_user_action`: the exact user action needed, with the resume point after it is done

Effect(효과): `blocked(차단)` means the pass tried the narrow recovery path first, not merely that the missing work was noticed.

## MT5 Runtime Rule

For MT5(`MetaTrader 5`, 메타트레이더5), MetaEditor compile(메타에디터 컴파일) is not enough when the requested product is MT5 snapshot(MT5 스냅샷), terminal file output(터미널 파일 출력), strategy tester output(전략 테스터 출력), or runtime parity(런타임 동등성).

Required behavior:

1. If the checked-in MQL5 tool is stale, create or patch a narrow current-project script/EA before blocked reporting.
2. Try to run it through the available terminal path, command-line path, or explicit user terminal action.
3. If Codex cannot drive the MT5 terminal, ask for the exact terminal action and name the output file that should appear.
4. Report `blocked` only with recovery attempt(복구 시도), execution attempt(실행 시도), failure log(실패 로그), or required user action(필요 사용자 행동).

## Guardrails

- If source data is missing, do not create processed outputs as if the source data existed.
- If the required tool or runtime is missing, do not simulate success unless the task is explicitly to create a mock.
- If the job is to build a tool, do not turn the pass into repeated source-data auditing unless new evidence makes that necessary.
- If material is required and missing, name the shortest current-project path to restore or regenerate it.
- If Codex can remove the blocker within available permissions, remove it before reporting `blocked`.
- If user cooperation is required, ask for the exact setup, credential, local data, terminal action, or permission needed and state the resume point.
- If verification cannot run, name whether the blocker is material, tool, environment, or permission.
- Do not treat compile-only evidence as runtime output when the requested artifact is a runtime snapshot or terminal-generated file.
- If the original goal changes, say that it changed before proceeding.
- Do not close the task with a polished report that only explains why the real work did not happen.

## Good Outcome

The user should be able to tell:

- what was supposed to be made
- what was actually available
- what was missing
- whether the work stayed on target
- what single next action removes the blocker
