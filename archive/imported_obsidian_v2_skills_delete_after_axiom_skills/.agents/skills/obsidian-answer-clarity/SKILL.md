---
name: obsidian-answer-clarity
description: Explain Project Obsidian Prime v2 work in plain, beginner-readable language without shrinking the substance. Strongly trigger for planning, proposed plans, result reports, completion reports, status summaries, reviews, PR explanations, decision notes, or any user-facing answer that contains project terms, trading terms, engineering terms, or agent-policy terms.
---

# Obsidian Answer Clarity

Use this skill whenever the answer is meant for the user, not only for another engineer.

Default assumption: the user should not need to ask a second time for a plain explanation. Every project report should be understandable to a smart beginner while keeping the technical meaning intact.

## Automatic Bundle

For user-facing status summary(상태 요약), result report(결과 보고), completion report(완료 보고), plan(계획), or review explanation(검토 설명), apply this skill after the technical skill and pair it with `obsidian-claim-discipline`.

Effect(효과): current meaning(현재 의미), not-yet-true boundary(아직 사실 아님 경계), and next action(다음 행동)을 쉽게 말하면서도 claim(주장)이 강해지지 않는다.

## Strong Triggers

This skill is mandatory, not optional, for:

- planning replies(plan, 계획), including proposed plan(제안 계획) and next-task plan(다음 작업 계획)
- result reports(결과 보고), completion reports(완료 보고), and status summaries(상태 요약)
- stage closeout(단계 종료), handoff(인계), run result(실행 결과), review finding(검토 발견사항), or failure report(실패 보고)
- answers after implementation(구현 후 답변), verification(검증), or file edits(파일 수정)
- run packaging, individual experiment closeout, KPI interpretation, artifact handoff, PR summary, or policy/skill review

If another skill produced a technical result, apply this skill last before answering the user.

## Purpose

Make the answer easy enough for a non-developer and trading non-specialist to follow, while keeping the full meaning.

Do not treat Korean parallel notation as explanation by itself. A term like `runtime_authority(런타임 권위)` still needs a plain meaning.

## Required Behavior

1. When using a specialist term, add the simple meaning near it.
2. Explain why the point matters.
3. Explain the effect on the project or the next decision.
4. Separate what is true now from what is not yet true.
5. Keep the answer complete; do not make it short by removing important reasoning.
6. Use a simple analogy when it makes the idea easier, but do not let the analogy replace the actual project meaning.
7. When explaining a finding, say:
   - what is wrong
   - why it can hurt the project
   - what a safe fix does

## Preferred Shape

For planning replies(plan, 계획):

- Start with the intended outcome in one plain sentence.
- Then name what will change and what will not change.
- Then name the verification/check that proves the plan worked.
- Then list exact files, runs, stages, or artifacts only when needed.

For result reports(결과 보고):

- Start with the result in one plain sentence.
- Explain the plain meaning before the dense technical details.
- Say what is true now.
- Say what is not yet true.
- Say why it matters for the next project decision.
- Name the next practical step.
- Then list exact files, runs, stages, artifacts, or tests only when they help the user act.

For run, experiment, package, or PR closeout:

- `Conclusion`: what changed or what the result means.
- `Plain meaning`: explain it as if the reader is new to coding and trading research.
- `Confirmed`: what the evidence now supports.
- `Not yet confirmed`: what must not be claimed yet.
- `Evidence`: commands, KPI, files, artifacts, hashes, or PR links when useful.
- `Next action`: the smallest useful follow-up.

## Do Not

- Do not answer with term pairs only, such as `runtime authority(런타임 권위)`, without a plain explanation.
- Do not hide uncertainty behind formal wording.
- Do not use a defensive phrase like "noted for future work" unless the missing work, blocker, and next condition are clear.
- Do not over-compress the answer when the user is asking for understanding.
- Do not lead user-facing result reports with a file inventory, command log, or test log.
- Do not bury the stage meaning behind implementation detail.
- Do not make the user ask "what does this mean?" after a normal completion report.
- Do not use a specialist term as the main explanation when a plain sentence can carry the meaning.

## Example Standard

Instead of:

`runtime_authority` is not closed.

Write:

`runtime_authority(런타임 권위)` is not closed. Plainly, this means the project has not yet proven that the live or MT5 runtime path can be trusted as an operating handoff. The effect is that we can still use the current artifact for research planning, but we should not describe it as ready for live-like operation.
