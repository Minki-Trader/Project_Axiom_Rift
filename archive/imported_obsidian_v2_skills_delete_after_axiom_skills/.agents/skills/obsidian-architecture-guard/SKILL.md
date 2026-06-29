---
name: obsidian-architecture-guard
description: Guard Project Obsidian Prime v2 against stage-agnostic architecture and code-surface drift. Use when work touches feature calculation, model training/export, pipeline materialization, artifact claims, architecture debt, code placement, path identity, Windows long-path handling, stage transitions, alpha search, repo-scoped skills, agent settings, or Korean BOM/encoding-sensitive docs.
---

# Obsidian Architecture Guard

Use this skill when a task can change architecture meaning (구조 의미), not only when a specific stage number is involved.

## Trigger Surface

Use this guard for work touching any of:

- feature calculation (피처 계산)
- model training or export (모델 학습 또는 내보내기)
- pipeline materialization (파이프라인 물질화)
- artifact registry or artifact claims (산출물 등록부 또는 산출물 주장)
- code placement or reusable logic ownership (코드 배치 또는 재사용 로직 소유권)
- stage transition or alpha search (단계 전환 또는 알파 탐색)
- repo-scoped skills or agent settings (저장소 범위 스킬 또는 에이전트 설정)
- work packet routing, skill bundles, or final answer filters
- durable path references, archive behavior, or long artifact names (지속 경로 참조, 아카이브 동작, 긴 산출물 파일명)
- Korean `.md` or `.txt` docs (한국어 문서)

Do not key this guard to Stage 06 or Stage 07 only. It applies to all future stages.

## Must Read

- `docs/policies/architecture_invariants.md`
- `docs/registers/architecture_debt_register.md`
- `docs/policies/agent_trigger_policy.md` when routing or skills change
- `docs/policies/reentry_order.md` when re-entry behavior changes
- `docs/policies/exploration_mandate.md` when alpha-search framing or exploration discipline changes
- the touched skill or policy files

## Required Output

Every architecture-sensitive packet or summary must include:

- `architecture_risk`: whether the work can move ownership, source of truth, model identity, alpha-search meaning, or encoding state
- `debt_interaction`: whether it touches registered architecture debt
- `allowed_debt_change`: `reduce`, `leave_unchanged`, or `blocked_without_decision`
- `encoding_check`: whether Korean docs or repo-scoped skills need UTF-8 with BOM validation
- `line_ending_check`: whether touched text files preserve a stable LF/CRLF line-ending surface and avoid mixed line endings
- `path_safety_check`: whether repo-relative paths are used for durable identity, whether absolute paths are local-only, and whether Windows long path risk is controlled
- `code_surface_check`: whether owner module, caller, input/output, and artifact/report effect must be named
- `skill_routing_check`: whether `obsidian-work-packet-router` considered the full skill inventory and attached answer clarity plus claim discipline for the final user-facing report

## Guardrails

- Do not treat existing architecture debt as normal style.
- Do not describe a model as `materialized` unless a model artifact or frozen parameter/spec bundle exists.
- Do not add reusable feature logic to a stage script or orchestration pipeline when it belongs in `foundation/features`.
- Do not create all-in-one EA or pipeline monoliths when reusable logic can live in a smaller owner module.
- Do not leave repo-scoped skills present but unrouted; every skill needs routing policy and agent metadata unless a durable exception explains why.
- Do not let alpha search become source cleanup only unless a durable decision says so.
- Do not store absolute terminal install paths as artifact identity; use repo-relative paths plus hash, run id, bundle id, or registry fields.
- For deep stage, MT5, or packet artifact trees, make the first discovery command repo-relative `rg --files`/`rg`; do not start with broad recursive PowerShell, `Test-Path`, `Resolve-Path`, `Import-Csv`, or `Measure-Object`. After discovery, make the first content read/existence check through `foundation.control_plane.ledger.io_path`, `path_exists`, or a helper built on them; do not start with `Path.read_text`, `Path.read_bytes`, `Path.open`, `Path.exists`, PowerShell `Get-Content`, `Import-Csv`, or pandas direct paths. Effect(효과): long-path safety(긴 경로 안전성)가 final judgment(최종 판정)이 아니라 first tool/read choice(첫 도구/읽기 선택)에 걸린다.
- Do not call(판정) a file missing(누락) when one tool(도구)이 enumerates it(나열) but another path API(경로 API)가 fails(실패)한다; rule out Windows long-path handling(윈도우 긴 경로 처리)을 먼저 확인한다.
- Prefer(선호) ZIP plus manifest(ZIP+목록) for deep archive snapshots(깊은 보관 스냅샷), and keep `\\?\` long-path prefixes(긴 경로 접두사)는 local tooling(로컬 도구)에만 두고 committed docs(커밋 문서)에는 남기지 않는다. For stage/MT5 artifact reads(단계/MT5 산출물 읽기), use repo-relative `rg --files`/`rg` and `foundation.control_plane.ledger.io_path` before changing durable path identity(지속 경로 정체성).
- Before creating or editing Korean `.md/.txt`, repo-scoped skills, or policy/control-plane markdown, classify the encoding surface and run scoped encoding validation or an equivalent byte-level BOM/UTF-8/mojibake check for existing targets. New Korean docs must be created as UTF-8 with BOM from the first write. Effect(효과): encoding safety(인코딩 안전성)가 final validation(최종 검증)이 아니라 first write choice(첫 쓰기 선택)에 걸린다.
- Do not treat Git LF/CRLF warnings as encoding failure. Before broad mechanical rewrites, classify the line-ending surface and preserve the existing convention unless the packet explicitly repairs it. Mixed line endings should be surfaced as a warning or scoped repair target. Effect(효과): line-ending churn(줄 끝 변동)이 encoding repair(인코딩 수리)나 evidence diff(근거 차이)를 숨기지 못하게 한다.
- Do not edit Korean `.md` or `.txt` docs without preserving UTF-8 with BOM. If a touched file already has encoding debt(인코딩 부채), explicitly repair that touched surface or lower the claim to blocked/plan-only(차단/계획 전용); do not silently add new content on top of mojibake(문자 깨짐), repeated BOM(반복 BOM), or invalid UTF-8(유효하지 않은 UTF-8).

## Validator

Run `scripts/validate_agent_settings.py --repo-root .` after editing agent settings, repo-scoped skills, architecture policies, debt registers, or Korean docs.

The validator intentionally treats `agents/openai.yaml` as a small repo-local format: top-level `interface:` and `policy:` sections with two-space indented one-line scalar fields. If richer YAML is needed later, add an explicit YAML dependency and update the validator instead of silently relying on unsupported syntax.

If the full validator fails because of already recorded historical encoding debt(기록된 과거 인코딩 부채), also run `scripts/validate_agent_settings.py --repo-root . --encoding-scope <repo-relative-path>` for each changed Korean `.md` or `.txt` surface and record both results. Effect(효과): the full backlog(전체 백로그)은 숨기지 않으면서 the current patch(현재 패치)가 new mojibake/BOM debt(새 문자 깨짐/BOM 부채)를 만들었는지 분리한다.

For deep stage paths(깊은 단계 경로), scoped encoding validation(범위 인코딩 검증)은 repo-relative path(저장소 상대 경로)를 받되, internally(내부적으로) `foundation.control_plane.ledger.io_path(입출력 경로 보조)`로 existence/read(존재/읽기)를 확인해야 한다. Effect(효과): Windows MAX_PATH(윈도우 경로 길이 한계) 때문에 존재하는 Korean report(한국어 보고서)를 missing(누락)으로 오판하지 않는다.

The validator reports mixed line endings as warnings, not encoding errors. Effect(효과): LF/CRLF(줄 끝 형식) noise(소음)는 실패로 과장하지 않고, real mixed-line files(실제 혼합 줄 끝 파일)만 후속 수리 대상으로 보이게 한다.
