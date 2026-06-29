---
name: obsidian-grok-collaboration
description: Retired/archive-only Project Obsidian Prime v2 skill for reading historical Grok review records. Use only when Codex needs to inspect old docs/agent_control/grok_reviews artifacts, old Grok receipts, or migration evidence. Do not call Grok, create prompts, create outputs, create receipts, add gates, or route external review through Grok; route critique, second opinion, no-solo-Codex, stage-close adversarial review, and agent/skill consulting to obsidian-task-force-review.
---

# Obsidian Grok Collaboration

This skill is retired/archive-only(퇴역/보관 전용).

## Allowed Use

Use this skill only to read historical Grok records(과거 그록 기록), such as:

- `docs/agent_control/grok_reviews/`
- old Grok receipt(과거 그록 영수증)
- old stage report(과거 단계 보고서) that cites Grok
- migration evidence(전환 근거) proving Grok was not used as active authority

Effect(효과): old evidence(과거 근거)를 보존하면서 new operating direction(새 운영 방향)이 Grok(그록)으로 되돌아가지 않게 한다.

## Forbidden Use

Do not:

- call Grok(Grok 호출)
- create a Grok prompt(그록 프롬프트)
- create Grok output(그록 출력)
- create a new Grok receipt(그록 영수증)
- add a Grok gate(그록 게이트)
- run `foundation/control_plane/grok_review_wrapper.py`
- treat external review(외부 리뷰), second opinion(2차 의견), no-solo-Codex judgment(코덱스 단독 판단 금지), stage-close adversarial review(단계 마감 비판 검토), or agent/skill consulting(요원/스킬 상담) as a Grok trigger(그록 트리거)

Route those requests to `obsidian-task-force-review(태스크포스 검토)`.

Effect(효과): user wording(사용자 표현)이 Grok(그록) 호출로 역류하지 않고, Codex Task Force(코덱스 태스크포스)가 검토 책임을 가진다.

## Archive Read Workflow

1. Confirm the task is read-only historical inspection(읽기 전용 역사 확인).
2. Locate the relevant record with `rg --files` before opening variant paths.
3. Read only the smallest sufficient file: receipt(영수증), metadata(메타데이터), clean output(정리 출력), or report(보고서).
4. Classify the old Grok record as historical evidence(역사 근거), not current advice(현재 조언).
5. Restate claim boundary(주장 경계): historical Grok records cannot create completion(완성), selected baseline(선택 기준선), operating promotion(운영 승격), runtime authority(런타임 권위), live readiness(실거래 준비), or Goal Achieve(목표 달성).

## Handoff

For any current review, critique, direction debate, stage closeout, model/risk challenge, policy/skill governance, or multi-agent consultation, stop using this skill and use `obsidian-task-force-review(태스크포스 검토)`.
