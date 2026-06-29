---
name: obsidian-claim-discipline
description: Enforce claim discipline in Project Obsidian Prime v2 by downgrading planning or pending states, separating parity levels, and preventing overstatement of closure or readiness. Use when writing docs, reviews, status notes, or user-facing summaries.
---

# Obsidian Claim Discipline

Use this skill when writing, editing, or summarizing project state.

## Automatic Companion

Run this skill as the companion check for user-facing report(사용자 보고), run evidence(실행 근거), stage transition(단계 전환), promotion(승격), runtime(런타임), and blocker(차단 사유) work.

Effect(효과): claim boundary(주장 경계)를 낮출 곳은 낮추고, closure(종료), positive judgment(긍정 판정), operating promotion(운영 승격), runtime authority(런타임 권위)를 근거 없이 쓰지 않는다.

## Trigger Tokens

If any relevant field contains one of these tokens, switch into strict claim discipline:

- `pending_*`
- `planning_*`
- `draft`
- `placeholder_*`
- `not_yet_evaluated`
- `not_applicable`

## Required Behavior

1. Do not describe pending or planning artifacts as:
   - `closed`
   - `materialized`
   - `durable`
   - `parity-closed`
   - `exploration-ready`
   - `alpha-ready`
   - `feature-layer ready`
   - `model materialized`
2. Use precise language:
   - `planning scaffold`
   - `materialized evidence`
   - `foundation truth`
   - `operating truth`
   - `model-input parity`
   - `runtime-helper parity`
   - `bundle handoff verification`
   - `broader-sample parity`
   - `probability-output evidence`
   - `frozen model artifact`
   - `architecture debt`
   - `exploration evidence`
   - `promotion-ineligible`
   - `promotion_candidate`
   - `operating_promotion`
   - `runtime_probe`
   - `runtime_authority`
   - `idea-dead`
   - `tier_c_local_research`
3. If a closure claim is made, name the backing artifact, report, or decision memo.
4. If legacy evidence is referenced, mark it `prior evidence only`.
5. If local-only artifacts are relied upon, ensure their identity is represented in `docs/registers/artifact_registry.csv` before describing them as reusable.
6. Do not let `README.md` or another overview doc carry mutable live-state claims unless they are synchronized in the same pass; prefer pointers to the authoritative current-truth docs.
7. Do not describe a model as materialized unless a reproducible model artifact or frozen parameter/spec bundle exists.
8. Do not describe `foundation/features` or another reusable feature layer as ready when reusable logic still lives only in a pipeline or stage-local script.
9. Do not treat registered architecture debt as a normal pattern to inherit.
10. Do not describe a promotion-ineligible idea as worthless, dead, or fully closed unless negative-result memory records why it failed, what was salvaged, and when to reopen it.
11. Do not describe Tier C local research as a trading lane, reduced-risk substitute, or promotion argument.
12. Do not describe a legacy lesson as v2 truth unless a v2 artifact closes the same question.
13. Do not confuse `negative` (`부정`) with `invalid` (`무효`); a negative result is interpretable evidence, while an invalid result is not.
14. Do not describe `inconclusive` (`불충분`) as success, closure, or failure unless the missing evidence and remaining question are named.
15. Do not call a run `reviewed`, `selected`, `archived`, or `closed` unless measurement evidence, managed identity, and lane-aware judgment are present or explicitly marked `n/a` with reasons.
16. Do not describe `promotion_candidate` (`승격 후보`) as `operating_promotion` (`운영 승격`).
17. Do not describe `runtime_probe` (`런타임 탐침`) as `runtime_authority` (`런타임 권위`) or runtime parity closure.

## Project-Specific Guardrails

- `planning scaffold` is not `materialized evidence`.
- `foundation truth` is not `operating truth`.
- `foundation stage closure` is not `exploration-ready`.
- `handoff verification` is not `runtime parity closure`.
- `probability-output evidence` is not a `frozen model artifact`.
- `architecture debt` is not an accepted architecture pattern.
- `promotion-ineligible` is not `idea-dead`.
- `tier_c_local_research` is not a runtime lane.
- `legacy exploration spirit` is not `legacy result inheritance`.
- `negative` is not `invalid`.
- `inconclusive` is not quiet approval.
- `structural_scout` is not an operating promotion read.
- `promotion_candidate` is not `operating_promotion`.
- `runtime_probe` is not `runtime_authority`.
