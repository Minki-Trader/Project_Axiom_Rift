---
name: obsidian-lane-classifier
description: Classify Project Obsidian Prime v2 work into exploration, evidence, promotion, runtime, or extra lanes before planning or implementation. Use when a task involves alpha search, stage work, tiered readiness, promotion, runtime verification, extra stages, or ambiguous user intent that could mix exploration and operating discipline.
---

# Obsidian Lane Classifier

Use this skill before a task packet or implementation when lane confusion could change the required discipline.

## Automatic Bundle

Trigger automatically when a task mixes lane(레인), exploration(탐색), evidence(근거), promotion(승격), runtime(런타임), Tier A/B/C(티어 A/B/C), hard gate(강한 게이트), operating_promotion(운영 승격), or runtime_authority(런타임 권위) language.

Effect(효과): hard gate(강한 게이트)를 exploration permission(탐색 허가)으로 잘못 쓰지 않고, operating discipline(운영 규율)이 필요한 주장만 강하게 막는다.

## Must Read

- `docs/policies/exploration_mandate.md`
- `docs/policies/promotion_policy.md` when promotion is possible
- `docs/policies/tiered_readiness_exploration.md` when Tier A/B/C readiness is involved

## Lane Definitions

- `exploration`: create, mutate, stress, and learn from ideas.
- `evidence`: make results comparable, inspectable, and reusable.
- `promotion`: decide whether a candidate can replace or confirm the operating line.
- `runtime`: verify execution, parity, packaging, and environment behavior.
- `extra`: user-requested side stage or non-standard question with its own charter.

## Required Output

- `lane`: one primary lane
- `secondary_lane`: optional supporting lane
- `discipline`: `exploration_discipline`, `operating_discipline`, or `handoff_discipline`
- `promotion_state`: `none`, `promotion_candidate`, or `operating_promotion`
- `runtime_state`: `none`, `runtime_probe`, or `runtime_authority`
- `promotion_gate_applicable`: `yes` or `no`
- `runtime_gate_applicable`: `yes` or `no`
- `hard_gate_applicable`: `yes` only for operating truth claims
- `failure_memory_required`: `yes` or `no`

## Guardrails

- Do not apply operating-promotion or runtime-authority gates to early exploration unless the task asks for an operating truth claim.
- Allow `promotion_candidate` and `runtime_probe` when the evidence boundary is explicit.
- Do not call an idea worthless because it is blocked for promotion.
- Do not let an `extra` stage bypass Tier A/B/C, WFO defaults, artifact identity, or runtime parity rules.
- If the user intent is informal, infer the lane from the work effect and state the inference.
