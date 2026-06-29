---
name: obsidian-session-intake
description: Start each Project Obsidian Prime v2 turn by establishing current truth, deciding cold re-entry versus warm-thread delta check, and handing the request to a project-wide work-packet router instead of treating code, experiment, evidence, and report as separate modes.
---

# Obsidian Session Intake

Use this skill at the start of a working turn when the user asks for current status, next work, implementation, verification, publishing, or a project-policy change.

This is an intake skill, not a single-mode classifier. Most Obsidian work is a multi-phase packet: design, code, experiment or verification, evidence, judgment, and user-facing report often belong to one request.

## When To Trigger

- a new thread starts in this repo
- work resumes after a pause
- the user asks for current progress, current state, or the next task
- the user asks to proceed but no current task packet is fixed yet

## Do First

1. Decide whether the thread is cold or warm.
2. If the thread is warm and the active stage is stable, prefer a delta check instead of repeating full cold re-entry.
3. Check whether the current branch/worktree matches the requested stage, PR, experiment, or policy scope.
4. Identify the likely work packet lifecycle and candidate `primary_family`. Do not force a single mode when the work naturally spans several phases.
5. Hand the lifecycle and candidate family to `obsidian-work-packet-router` so it can choose exactly one `primary_family`, one `primary_skill`, limited `support_skills`, and `required_gates`.
6. Decide whether the requested turn is architecture-sensitive: feature/model/pipeline/artifact, alpha-search framing, stage transition, repo-scoped skill, agent setting, or Korean encoding work.
7. Decide whether the requested turn is exploration-sensitive: alpha search, idea variants, Tier B/C research, WFO planning, extreme sweep, negative-result closure, or user-requested extra stage.
8. Decide whether the requested turn is run-evidence-sensitive: run creation, run closeout, KPI report, result summary, result judgment, or run registry update.
9. Decide whether the requested turn is reproducibility-sensitive: clean checkout, dependency, CI, artifact path, MT5 terminal path, or external environment setup.

## Must Read

- `docs/workspace/workspace_state.yaml`
- `docs/context/current_working_state.md` when the current read needs support
- the active stage `04_selected/selection_status.md`
- `docs/policies/agent_trigger_policy.md`
- `docs/policies/branch_policy.md`
- the latest durable decision memo only when it changes current meaning or the user asks why
- `docs/policies/architecture_invariants.md` and `docs/registers/architecture_debt_register.md` when the requested turn is architecture-sensitive
- `docs/policies/exploration_mandate.md`, `docs/registers/idea_registry.md`, and `docs/registers/negative_result_register.md` when the requested turn is exploration-sensitive
- `docs/policies/kpi_measurement_standard.md`, `docs/policies/run_result_management.md`, `docs/policies/result_judgment_policy.md`, and `docs/registers/run_registry.csv` when the requested turn is run-evidence-sensitive

## Delta Reentry Mode

For a warm thread(따뜻한 스레드) with stable active stage(활성 단계), use `reentry_mode: delta(재진입 모드: 변화분)` unless a mismatch appears.

Delta checklist(변화분 점검표):

- active stage/current run(활성 단계/현재 실행)
- branch/worktree fit(브랜치/작업트리 적합성)
- user intent change(사용자 의도 변화)
- blocker or gate status change(차단 또는 게이트 상태 변화)
- touched surface(수정 표면): policy/skill, code, MT5/runtime, run evidence, publish

Escalate to `reentry_mode: cold(재진입 모드: 냉시작)` when any checklist item conflicts, a durable decision is unclear, or the user asks for broad state reconstruction. Effect(효과): stable follow-up work(안정된 후속 작업)가 22-doc full pass(22문서 전체 통과)로 커지지 않는다.

## Must Output

For low-risk `information_only` turns(낮은 위험 정보 작업), output(출력)은 compact(압축)할 수 있다. For code/experiment/MT5/policy/publish/ambiguous work(코드/실험/MT5/정책/발행/애매한 작업), expand the fields below.

- `intake_context`
- `reentry_mode`: `delta` or `cold`
- `current_truth_reference`
- `branch_worktree_fit`
- `branch_action`
- `active_stage`
- `work_packet_lifecycle`
- `primary_family_candidate`
- `routing_handoff`: the exact handoff to `obsidian-work-packet-router`
- `sensitivity_flags`: architecture, exploration, run_evidence, reproducibility, policy_skill_governance as applicable
- `allowed_scope`
- `stop_conditions`
- `publish_default`
- `final_answer_filter`

The router, not intake, owns final `primary_family`, `primary_skill`, `support_skills`, `skills_selected`, `skills_not_used`, `required_skill_receipts`, and `required_gates`. Intake may suggest them only as candidates.

## Do Not

- repeat full cold re-entry inside the same stable thread when a narrower delta check is enough
- invent a new active stage or reopen a closed stage from chat momentum alone
- let orientation docs outrank `workspace_state.yaml`, stage selection status, or durable decisions
- drift from status intake straight into implementation without first fixing the lifecycle and skill route
- work on a branch/worktree whose scope does not match the requested stage, PR, experiment, or policy packet
- treat code, experiment, evidence, and report as mutually exclusive categories
- stop after code edits when the request naturally requires verification, evidence, judgment, or user-facing explanation
- ignore architecture debt when the turn touches feature/model/pipeline/artifact, alpha-search, stage-transition, skill, agent-setting, or encoding work
- let promotion/runtime discipline block exploration before classifying the lane
- treat promotion-ineligible ideas as worthless ideas
- treat a run as reviewed or closed before measurement, management, and judgment are named

## Stop Conditions

- `workspace_state.yaml` and the active stage `selection_status.md` disagree on the active stage
- a durable decision memo contradicts the supposed current boundary
- the requested turn would cross from status or planning into implementation without an approved lifecycle packet
- the current branch/worktree is scoped to different work and switching would risk mixing unrelated changes

## Verification

- check that the named active stage is the same across the current truth sources you used
- check that the branch/worktree matches the requested work packet, or record the switch/new-branch/stop decision
- if a current task packet already exists, confirm it still fits the active stage and current durable decisions
- confirm that `obsidian-work-packet-router` receives the lifecycle and candidate `primary_family` unless the turn is strictly informational
- if architecture-sensitive, confirm whether the architecture guard validator is part of the verification surface
- if exploration-sensitive, confirm whether `obsidian-lane-classifier` and `obsidian-exploration-mandate` are part of the planning surface
- if run-evidence-sensitive, confirm whether `obsidian-run-evidence-system` is part of the planning surface

## Completion Criteria

- one lifecycle and one candidate `primary_family` are named, even if the lifecycle contains several phases
- branch/worktree fit is explicit before file edits
- the allowed scope and publish default are explicit enough that the next step can stay narrow
- skill selection is handed to the router instead of being attached broadly during intake
- `obsidian-answer-clarity` and `obsidian-claim-discipline` are named as the final user-facing filter when an answer will be sent
- architecture-sensitive work is routed to `obsidian-architecture-guard` regardless of active stage number
- exploration-sensitive work is routed by lane rather than by active stage number
- run-evidence-sensitive work is routed to measurement, management, and judgment rules before closeout
