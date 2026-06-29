---
name: obsidian-stage-transition
description: Open, close, or hand off stages in Project Obsidian Prime v2 without state fragmentation. Use when active_stage changes, a stage is closed, or work is passed to the next foundation stage.
---

# Obsidian Stage Transition

Use this skill whenever a stage opens, closes, or hands work to another stage.

## Automatic Bundle

When this skill triggers for stage transition(단계 전환), active_stage(활성 단계) change, closeout(종료), handoff(인계), workspace_state(작업공간 상태), selection status(선택 상태), or registry(등록부) sync, pair it with `obsidian-claim-discipline`.

Effect(효과): same-pass sync(같은 회차 동기화)와 claim boundary(주장 경계)를 함께 지켜서 단계 상태가 조각나지 않는다.

## Required Sync Pass

Use the canonical same-pass sync norm from `docs/policies/agent_trigger_policy.md`.

Update in the same pass:

- `docs/workspace/workspace_state.yaml`
- `docs/context/current_working_state.md`
- current or closing stage `04_selected/selection_status.md`
- current or closing stage `03_reviews/review_index.md` when needed
- next stage `00_spec/stage_brief.md`
- next stage `01_inputs/input_refs.md`
- `docs/decisions/*.md` when the transition is durable
- `docs/registers/artifact_registry.csv` when dataset, bundle, runtime, or report identity rows are added or superseded
- `docs/registers/run_registry.csv` when run identity, result status, or result judgment changes durably
- `docs/workspace/changelog.md`
- `README.md` when it still contains mutable stage, closure, or current-mode wording that this transition would otherwise leave stale
- `docs/policies/architecture_invariants.md` and `docs/registers/architecture_debt_register.md` when the transition changes feature/model/pipeline/artifact ownership, alpha-search framing, or encoding-sensitive agent behavior
- `docs/policies/exploration_mandate.md`, `docs/registers/idea_registry.md`, and `docs/registers/negative_result_register.md` when the transition opens, closes, archives, or hands off exploration work
- `docs/policies/kpi_measurement_standard.md`, `docs/policies/run_result_management.md`, and `docs/policies/result_judgment_policy.md` when the transition changes run evidence rules or closes a stage based on run results

## Transition Rules

1. Never close a stage by implying later-stage evidence is already complete.
2. Give every remaining blocker an explicit downstream home.
3. Preserve the difference between:
   - planning closure
   - dataset-contract closure
   - runtime parity closure
   - artifact identity closure
4. Keep `active_stage` aligned everywhere after the transition.
5. Derive current and next stage names from `docs/workspace/workspace_state.yaml`, decision memos, and stage docs; do not hard-code the active stage name in this skill.
6. Prefer replacing volatile `README.md` status snapshots with pointers to the authoritative current-truth docs instead of maintaining a second live-state ledger there.
7. Do not let a new stage inherit registered architecture debt as if it were normal project style.
8. If the transition opens alpha search, separate source cleanup or validation debt closure from the actual alpha-search question.
9. If the transition opens a user-requested extra stage, require charter, lane, question, allowed evidence, exit condition, and no-promotion boundary unless a promotion packet is explicitly opened.
10. If the transition closes exploration, require negative-result memory or a positive archive record before treating the idea as durable knowledge.
11. If the transition closes a run-producing stage, require run measurement, managed identity, and lane-aware judgment for the selected or archived run evidence.
12. If the transition closes a frontier stage(전선 단계), run `frontier_extra_stage_due_check(전선 추가 단계 도래 점검)` first, then record `frontier_five_stage_direction_synthesis(전선 5단계 방향 종합)`, then run `frontier_topic_rotation_check(전선 주제 회전 점검)` before opening the next canonical frontier stage(정식 전선 단계). The historical five-stage Grok retrospective(역사 5단계 그록 회고)는 archive-only(보관 전용)이며 next-open block(다음 개방 차단)을 만들지 않는다.
13. `frontier_topic_rotation_check(전선 주제 회전 점검)` must verify that repair disposition(수리 처분) closed inside the active stage(활성 단계), and that the next stage question(다음 단계 질문) is not continuation repair(연속 수리), near-duplicate hypothesis(근접 중복 가설), threshold/filter/session/routing/parameter-only tweak(임계값/필터/세션/라우팅/파라미터만 미세조정), or renamed repair(이름만 바꾼 수리).
14. `frontier_five_stage_direction_synthesis(전선 5단계 방향 종합)` is a light direction record(가벼운 방향 기록), not topic abandonment(주제 폐기) or topic ban(주제 금지). Same topic(같은 주제)은 later re-experiment(나중 재실험)할 수 있고, it only blocks adjacent same-axis continuation(인접 동일 축 연속).

## Validation

- after the sync pass, verify that `docs/workspace/workspace_state.yaml`, `docs/context/current_working_state.md`, and the active stage `selection_status.md` all name the same active stage
- before opening a frontier stage, verify `frontier_extra_stage_due_check(전선 추가 단계 도래 점검)`, `frontier_five_stage_direction_synthesis(전선 5단계 방향 종합)`, and `frontier_topic_rotation_check(전선 주제 회전 점검)` in that order; do not use historical five-stage Grok retrospective(역사 5단계 그록 회고) as an active gate(활성 게이트)
- if the transition changes durable meaning, make sure a `docs/decisions/*.md` memo exists in the same pass
- if architecture-sensitive docs or skills changed, run the architecture guard validator
- if exploration-sensitive docs or skills changed, verify that lane routing, WFO default, and failure-memory references are still linked from the trigger policy
- if run evidence docs or skills changed, verify that KPI measurement, run-result management, and result judgment references are still linked from the trigger policy

## Project-Specific Guardrails

- Do not hard-code durable ownership to a numbered stage.
- Derive each stage's current question, closure boundary, and handoff meaning from `docs/workspace/workspace_state.yaml`, the active stage docs, and durable decision memos.
- Do not pull runtime parity, artifact identity, or operating-promotion meaning into a stage unless the current truth sources explicitly put that work in scope.
