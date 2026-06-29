---
name: obsidian-experiment-design
description: Design project-wide trading research experiments by naming hypothesis, comparison, controls, stop conditions, success and failure criteria, and required evidence before code or runs are produced.
---

# Obsidian Experiment Design

Use this skill when a request creates, changes, compares, packages, or closes an experiment. It applies across the full project lifecycle, not only alpha exploration.

## Required Output

- `hypothesis`: what the experiment is trying to learn
- `decision_use`: what decision the result can influence
- `comparison_baseline`: what the result is compared against
- `control_variables`: settings that must stay fixed
- `changed_variables`: settings or code paths intentionally changed
- `sample_scope`: dataset, tier, symbol, timeframe, date range, or runtime scope
- `success_criteria`: what would count as useful evidence
- `failure_criteria`: what would count as a failed or negative result
- `invalid_conditions`: what would make the result unusable
- `stop_conditions`: when to stop, narrow, rerun, or downgrade claims
- `evidence_plan`: KPI, files, manifests, registry rows, and checks needed

## Guardrails

- Do not treat a run that merely completed as a meaningful experiment.
- Do not compare results if the baseline, data scope, or changed variable is unclear.
- Do not let an operating gate prevent research unless the claim is operating promotion or runtime authority.
- Do not design an experiment that cannot be explained later through `obsidian-answer-clarity`.
