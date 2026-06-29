---
name: obsidian-work-packet-router
description: Route each Project Obsidian Prime v2 request as a multi-phase work packet across design, code, experiment, verification, evidence, judgment, report, and publish phases; use project-wide and never bind routing to one stage.
---

# Obsidian Work Packet Router

Use this skill after session intake and before planning or implementation.

Most Obsidian requests are not one mode. A normal request may start with an idea, write code, run an experiment, record evidence, judge results, and explain the outcome to the user. Route the whole lifecycle before acting.

## Must Read

- `docs/policies/agent_trigger_policy.md`
- `docs/policies/branch_policy.md`
- `docs/policies/reentry_order.md` when current truth is uncertain
- `AGENTS.md`
- The SKILL.md files for any selected skills

## Required Output

- Always emit(항상 남김) `routing_receipt(라우팅 기록)`: lifecycle(생명주기), `primary_family(주 작업군)`, `primary_skill(주 스킬)`, selected `support_skills(보조 스킬)`, `required_gates(필수 게이트)`, and structured not-selected reasons(구조화된 미선택 사유)를 담은 compact record(압축 기록).
- `work_packet_lifecycle`: one of `information_only`, `design_only`, `code_to_verify_to_report`, `experiment_to_evidence_to_report`, `code_to_experiment_to_evidence_to_report`, `policy_skill_governance`, `publish_or_handoff`, or a short custom lifecycle(짧은 사용자 정의 생명주기)
- `router_mode`: `lite` for trivial/information_only(사소/정보 전용) work, otherwise `full`
- `phase_plan`: ordered phases(순서 있는 단계) for the current packet(현재 작업 묶음); low-risk `information_only`(낮은 위험 정보 작업)는 compact(압축), code/experiment/MT5/policy/publish/ambiguous work(코드/실험/MT5/정책/발행/애매한 작업)는 expanded(확장)
- `primary_family`: exactly one family(작업군) from `docs/agent_control/work_family_registry.yaml`
- `primary_skill`: exactly one primary skill(주 스킬) from that family
- `support_skills`: only the family-supported skills(보조 스킬) actually needed for this packet
- `skills_considered`: high-relevance repo-scoped skills(저장소 전용 스킬) considered for this packet
- `skills_selected`: normalized list(정규화 목록) equal to `primary_skill` followed by selected `support_skills`
- `skills_not_used`: attached(선택)하지 않은 high-relevance skills(고관련 스킬) with structured reasons such as `not_primary_family_required_skill`, `not_required_for_read_only`, or `enforced_as_required_gate_not_support_skill`; do not use vague "implicitly satisfied" wording
- `required_skill_receipts`: receipt-required skills(영수증 필수 스킬), matching `skills_selected` unless a gate explicitly enforces the responsibility
- `required_gates`: gates(게이트) that must execute in closeout or be declared N/A with a reason
- `skills_to_read`: primary skill(주 스킬) first, then support skills(보조 스킬) only when each has a one-line justification(한 줄 사유)
- `branch_worktree_fit`: whether the current branch/worktree matches the requested packet
- `branch_action`: stay, switch, create_new_branch, create_or_select_worktree, or stop_for_user
- `phase_stop_conditions`: where to stop or downgrade claims
- `final_answer_filter`: normally `obsidian-answer-clarity` plus `obsidian-claim-discipline`
- `handoff_surface`: files, registers, PR, artifact, or user action touched by the packet

## Default Phase Library

- reentry and current truth: `obsidian-reentry-read`
- lifecycle routing: `obsidian-session-intake`, then this skill
- branch/worktree fit: `docs/policies/branch_policy.md`
- architecture or policy: `obsidian-architecture-guard`
- code placement: `obsidian-code-surface-guard`
- implementation quality: `obsidian-code-quality`
- external correctness: `obsidian-reference-scout`
- experiment design: `obsidian-experiment-design`
- data and time integrity: `obsidian-data-integrity`
- model or threshold validation: `obsidian-model-validation`
- MT5 or live-like parity: `obsidian-runtime-parity`
- tester evidence: `obsidian-backtest-forensics`
- run evidence and registers: `obsidian-run-evidence-system`
- artifact lineage: `obsidian-artifact-lineage`
- environment reproducibility: `obsidian-environment-reproducibility`
- KPI explanation: `obsidian-performance-attribution`
- result boundary: `obsidian-result-judgment`, then `obsidian-claim-discipline`
- final user report: `obsidian-answer-clarity`

## Lite Router Mode

Use `router_mode: lite(라우터 경량 모드)` for read-only status(읽기 전용 상태), path/hash/register recount(경로/해시/등록부 재확인), or narrow review(좁은 검토) when the packet does not mutate files, run tools, publish/push, close a stage, touch MT5/runtime/model artifacts, or claim completed/reviewed/verified(완료/검토/검증).

Lite output(경량 출력) still names one primary_family(주 작업군) and one primary_skill(주 스킬), but support_skills(보조 스킬) default to 0 and gates(게이트) may be declared `not_applicable_with_reason(사유 있는 해당 없음)`. If the task crosses into mutation(수정), execution(실행), stage closeout(단계 마감), runtime/model work(런타임/모델 작업), or publish(게시), upgrade to `router_mode: full(라우터 전체 모드)`. Effect(효과): small work(작은 작업)를 기록 없이 처리하지 않으면서도 full packet overhead(전체 묶음 부담)를 피한다.

## Do Not

- Treat code, experiment, evidence, and report as mutually exclusive.
- Stop at code generation when the user asked for work that naturally requires verification or reporting.
- Work in a branch or worktree that belongs to a different stage, PR, experiment, or policy scope.
- Mix two open PR scopes in one worktree unless the user explicitly asks for that combined patch.
- Create stage-specific routing skills when a project-wide lifecycle responsibility fits.
- Skip answer clarity because a result is technically correct.
- Skip reference scouting silently; record why it was not required.
- Select broad automatic skill groups. The router chooses one primary family, one primary skill, and only the support skills that materially change execution or closeout evidence.
- Replace(대체) the compact routing receipt(압축 라우팅 기록)를 unrecorded private decision(기록 없는 내부 판단)으로 바꾸지 않는다; receipt(기록)는 abandoned skills(유기되는 스킬)을 막는 guard(가드)다.
