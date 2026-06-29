---
name: obsidian-task-force-review
description: Route Project Obsidian Prime v2 work through the permanent Codex Task Force roster. Use when changing AGENTS.md, repo skills, policy, work-family routing, receipt schemas, agent settings, five-stage retrospective behavior, or running Frontier80 open-to-closeout governance rehearsal.
---

# Obsidian Task Force Review

## Overview

Use this skill to run project-native Codex Task Force review(코덱스 태스크포스 검토) without treating Grok(그록) as inherited authority.

The skill adds a bounded internal review layer(제한 내부 검토층). It does not replace MT5 evidence(MT5 근거), runtime probes(런타임 탐침), gate coverage(게이트 커버리지), or claim discipline(주장 규율).

## Required Inputs

- Current truth(현재 진실): `docs/workspace/workspace_state.yaml`, `docs/context/current_working_state.md`, active selection status(활성 선택 상태).
- Roster registry(명단 등록부): `docs/agent_control/codex_task_force_registry.yaml`.
- Codex custom agent config(Codex 사용자 정의 요원 설정): `.codex/config.toml` and `.codex/agents/*.toml`.
- Work family routing(작업군 라우팅): `docs/agent_control/work_family_registry.yaml`.
- Active goal(`/goal`, 활성 목표), work packet(작업 묶음), router-selected required overlay(라우터 선택 필수 오버레이), or explicit user instruction requiring review(검토를 요구하는 명시 사용자 지시) with claim boundary(주장 경계).

## Workflow

1. Confirm the request is project-native Task Force work with an active review requirement(활성 검토 요구), not historical Grok archive lookup(과거 그록 보관 조회).
2. Do not treat Grok call/review wording(그록 호출/검토 문구) itself as a Task Force trigger(태스크포스 트리거). Grok has no active call path(활성 호출 경로 없음); historical Grok records(과거 그록 기록)는 archive-only(보관 전용)로만 읽는다.
3. Treat agent/skill consulting(요원/스킬 상담) as `micro_consult(소형 상담)` by default. It is advisory(자문) only and does not create a formal Task Force review gate(공식 태스크포스 검토 게이트).
4. Use formal Task Force review(공식 태스크포스 검토) only for stage closeout(단계 마감), policy change(정책 변경), runtime authority(런타임 권위), operating promotion(운영 승격), cross-system handoff(교차 시스템 인계), or an explicit protected reviewed/verified/pass claim(보호된 검토/검증/통과 주장).
5. Select the minimum necessary agents(요원) from the registry. Choose by packet claim surface(묶음 주장 표면), required gate(필수 게이트), and roster remit(명단 임무), not by habit(습관).
   - Default `micro_consult(소형 상담)` is 1 agent(요원 1명).
   - Use 2 agents(요원 2명) when the question crosses two remits(두 임무) or needs owner plus checker(소유자와 점검자).
   - Calling 3 or more agents(3명 이상 호출)는 `escalation_reason(확대 사유)`가 필요하다.
   - Calling 5 or more agents(5명 이상 호출)는 `why_not_smaller(왜 더 작게 못 했는지)`가 필요하다.
   - Calling all 8 agents(8명 전원 호출)는 `escalation_reason(확대 사유)`, `why_not_smaller(왜 더 작게 못 했는지)`, and `full_roster_call_reason(전원 호출 사유)`가 모두 필요하다.
   - The governance/evidence balance rule(운영/근거 균형 규칙) alone is not a Task Force trigger(태스크포스 트리거). It only changes routing when the current packet already needs consultation or review(상담 또는 검토).
6. Immediately call the selected agents(선택 요원) with real `spawn_agent(서브에이전트 생성 호출)` before making any Task Force reviewed/reviewed/verified/pass(태스크포스 검토됨/검토됨/검증됨/통과) claim.
   - Use the custom agent name(사용자 정의 요원 이름) matching the roster id(명단 ID) in `.codex/agents/<roster_id>.toml`.
   - If current Codex tool metadata(현재 코덱스 도구 메타데이터)가 not refreshed(미갱신) and the named custom agent(이름 지정 사용자 정의 요원)가 not callable(호출 불가)라면 optional `micro_consult(선택 소형 상담)`은 explicit roster-id prompt(명시 명단 ID 프롬프트)로 advisory_only(자문 전용) 기록만 남길 수 있다.
   - If formal Task Force review(공식 태스크포스 검토) is required by active goal(`/goal`, 활성 목표), packet(묶음), required gate(필수 게이트), family rule(작업군 규칙), router-selected required Task Force overlay(라우터 선택 필수 태스크포스 오버레이), explicit user instruction requiring review(검토를 요구하는 명시 사용자 지시), or closeout claim(마감 주장), unavailable or uncalled selected-agent `spawn_agent(선택 요원 서브에이전트 생성 호출)` sets status to `blocked_for_task_force_review(태스크포스 검토 차단)`.
   - Required formal review(필수 공식 검토) cannot pass as `not_applicable_with_reason(사유 있는 해당 없음)` and cannot support reviewed/verified/pass/stage closeout pass/internally_reviewed/rehearsed_control_plane(검토됨/검증됨/통과/단계 마감 통과/내부 검토됨/제어면 리허설됨).
   - If Task Force review(태스크포스 검토) is optional, Codex(코덱스) may proceed only without any Task Force review claim(태스크포스 검토 주장).
   - The receipt(영수증) must record each actual call(실제 호출) with `roster_agent_id(명단 요원 ID)`, `custom_agent_name(사용자 정의 요원 이름)`, `spawned_agent_id(생성 요원 ID)`, `tool_name=multi_agent_v1.spawn_agent(도구 이름)`, `result_status(결과 상태)`, and `opinion_classification(의견 분류)`.
7. Do not use dormant/stale agents(대기 중이거나 낡은 맥락의 요원) as review evidence without sending an explicit current context update(현재 맥락 갱신).
8. Apply the model policy(모델 정책): current floor `gpt-5.5 xhigh(5.5 매우 높음)`, future default `highest_available_xhigh(사용 가능 최상위 매우 높음)` unless the user pins a model.
9. Record bounded evidence(제한 근거). Prefer index-first/receipt-first(색인 우선/영수증 우선) reads before raw artifact expansion.
10. Limit adversarial review(비판 검토) to two passes: critique(비판) and owner response plus local verification(소유자 응답 + 로컬 검증). Start a third pass only when new evidence appears.
11. Classify each agent output as `accepted`, `rejected`, or `needs_local_verification(로컬 검증 필요)`.
12. Keep final authority with Codex(코덱스) local verification and project evidence, not the agent discussion itself.

## Micro Consult Receipt

`micro_consult(소형 상담)` is the default consultation path(기본 상담 경로). It creates advisory evidence(자문 근거) only, not reviewed/pass evidence(검토됨/통과 근거).

Required fields(필수 필드):

- `consult_id(상담 ID)`
- `parent_packet_id(상위 묶음 ID)`
- `trigger_source(트리거 원천)`
- `selected_agents(선택 요원)`
- `selection_reason(선택 사유)`
- `claim_surface(주장 표면)`
- `question_or_context_digest(질문 또는 맥락 요약)`
- `opinion_classification(의견 분류)`
- `owner_response(소유자 응답)`
- `local_verification_required(로컬 검증 필요 여부)`
- `allowed_claim_effect=advisory_only_no_reviewed_pass(허용 주장 효과=자문 전용, 검토/통과 아님)`
- `forbidden_claims(금지 주장)`

`micro_consult_index(소형 상담 색인)` may record consult_id/packet_id/timestamp/selected_agent_ids/topic/result_summary/claim_effect(상담 ID/묶음 ID/시각/선택 요원 ID/주제/결과 요약/주장 효과). It is findability metadata(검색용 메타데이터), not a gate pass(게이트 통과).

## Roster

Use the registry IDs, not ad hoc names:

1. `agent_01_system_governor(시스템 총괄)`
2. `agent_02_platform_routing_architect(플랫폼/라우팅 설계자)`
3. `agent_03_philosophy_policy_skill_governance(철학/정책/스킬 거버넌스 책임자)`
4. `agent_04_evidence_control_plane(근거/제어면 책임자)`
5. `agent_05_data_feature_contract(데이터/피처 계약 책임자)`
6. `agent_06_quant_research(정량 연구 책임자)`
7. `agent_07_model_validation_risk(모델 검증/위험 책임자)`
8. `agent_08_mt5_onnx_runtime(메타트레이더5/온엑스 런타임 책임자)`

## Claim Boundary

Task Force review(태스크포스 검토) can produce `internally_reviewed(내부 검토됨)` or `rehearsed_control_plane(제어면 리허설됨)` only when the matching evidence exists.

Matching evidence(일치 근거) requires actual selected-agent `spawn_agent(서브에이전트 생성 호출)` calls in the conversation before the claim. Self-review(자기검토), planned review(예정 검토), or stale agent output(낡은 요원 출력) is not Task Force review(태스크포스 검토).

`micro_consult(소형 상담)` can produce advisory notes(자문 기록) only. It cannot produce Task Force reviewed/reviewed/verified/pass/internally_reviewed/stage closeout pass(태스크포스 검토됨/검토됨/검증됨/통과/내부 검토됨/단계 마감 통과).

`tool_unavailable/not_called(도구 사용 불가/호출 안 됨)` is block evidence(차단 근거), not review evidence(검토 근거), whenever Task Force review(태스크포스 검토) is required.

It cannot produce completion(완성), selected baseline(선택 기준선), operating promotion(운영 승격), runtime authority(런타임 권위), live readiness(실거래 준비), Goal Achieve(목표 달성), or parity-only economics(동등성 단독 경제성).

## Frontier80 Rule

For Frontier80(전선80), do not reopen F79/F79A(전선79/79A). Treat F79 as closed negative memory(부정 기억) and preserved clue(보존 단서).

Frontier80(전선80) must rotate feature set, label, model family, trade shape, risk logic, and regime split(피처 묶음/라벨/모델 계열/거래 형태/위험 로직/장세 분할). The closeout boundary is runtime probe quality closeout(런타임 탐침 품질 마감), not runtime authority(런타임 권위).

## Do Not

- Do not call internal agents an external second opinion(외부 2차 의견).
- Do not label self-review(자기검토) as Task Force review(태스크포스 검토).
- Do not label `micro_consult(소형 상담)` as Task Force review(태스크포스 검토).
- Do not defer selected agent calls until closeout(마감) after already relying on a Task Force review(태스크포스 검토) claim.
- Do not treat `tool_unavailable/not_called(도구 사용 불가/호출 안 됨)` or `not_applicable_with_reason(사유 있는 해당 없음)` as a passing state for required Task Force review(필수 태스크포스 검토).
- Do not spawn all 8 agents(8명 전원) by default.
- Do not call 3 or more agents(3명 이상 요원) without `escalation_reason(확대 사유)`.
- Do not call 5 or more agents(5명 이상 요원) without `why_not_smaller(왜 더 작게 못 했는지)`.
- Do not omit `full_roster_call_reason(전원 호출 사유)` when all 8 agents(8명 전원)을 actually need to be called.
- Do not let agent consensus replace MT5 output(MT5 출력), ledger rows(장부 행), hashes(해시), or local filesystem verification(로컬 파일시스템 검증).
- Do not hand current review, critique, stage closeout, external review, or explicit Grok wording back to Grok(그록).
- Do not trigger active five-stage Grok retrospective(활성 5단계 그록 회고) during the Task Force migration path. Preserve historical records(역사 기록) instead.
- Do not use cheap local check(싼 로컬 점검) as a final conclusion. It is preflight(사전 점검) only.
