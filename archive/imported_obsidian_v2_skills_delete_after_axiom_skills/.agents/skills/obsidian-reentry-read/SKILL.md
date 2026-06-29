---
name: obsidian-reentry-read
description: Re-enter Project Obsidian Prime v2 safely by reading the current truth in order, restating the active stage and foundation status, and avoiding stale assumptions. Use when starting or resuming work in this repository.
---

# Obsidian Reentry Read

Use this skill whenever work starts or resumes inside `Project_Obsidian_Prime_v2`.

## Workflow

1. Open `AGENTS.md`, then open `docs/policies/reentry_order.md`.
2. Follow the canonical ordered pass and truth precedence defined there.
3. If the task touches feature/model/pipeline/artifact architecture, alpha-search framing, repo-scoped skills, agent settings, or Korean encoding, also read `docs/policies/architecture_invariants.md` and `docs/registers/architecture_debt_register.md`.
4. If the task touches exploration, idea variants, Tier B/C research, WFO planning, negative-result closure, legacy lessons, or user-requested extra stages, also read `docs/policies/exploration_mandate.md`, `docs/registers/idea_registry.md`, and `docs/registers/negative_result_register.md`.
5. If the task touches run creation, KPI reporting, result summaries, result judgment, or run closeout, also read `docs/policies/kpi_measurement_standard.md`, `docs/policies/run_result_management.md`, `docs/policies/result_judgment_policy.md`, and `docs/registers/run_registry.csv`.
6. Validate before acting:
   - `docs/workspace/workspace_state.yaml` names one active stage
   - the active stage `selection_status.md` agrees with that stage
   - the latest durable stage-handoff decision matches the same transition
   - before the first filesystem command that may touch a deep stage, MT5, or packet artifact tree, classify the path scope; if it is deep or broad, the first command must be repo-relative `rg --files`/`rg`, not broad recursive PowerShell, `Test-Path`, `Resolve-Path`, `Import-Csv`, or `Measure-Object`
   - after repo-relative discovery, use `foundation.control_plane.ledger.io_path`, `path_exists`, or a helper built on them for the first content read/existence check of deep stage, MT5, or packet artifacts; do not start with `Path.read_text`, `Path.read_bytes`, `Path.open`, `Path.exists`, PowerShell `Get-Content`, `Import-Csv`, or pandas direct paths
   - before the first write that may create or edit Korean `.md/.txt`, repo-scoped skills, or policy/control-plane markdown, classify the encoding surface; run scoped encoding validation or an equivalent byte-level BOM/UTF-8/mojibake check for existing targets, and plan a UTF-8 with BOM write path for new Korean docs
   - before broad mechanical text rewrites, classify LF/CRLF line endings and do not treat Git line-ending warnings as encoding failure; mixed line endings are a warning or scoped repair target
   - on Windows deep stage/MT5 paths, do not declare active-stage docs or frontier evidence `missing`, `invalid`, or `blocked` until repo-relative `rg --files`/`rg` has been attempted, and file content reads have used `foundation.control_plane.ledger.io_path`
   - if any of those disagree, stop and surface state fragmentation before continuing
7. Restate:
   - active stage
   - current foundation truth
   - current operating-truth boundary
   - what is planning only
   - what is materialized
   - what remains open
   - architecture debt interaction when relevant
   - exploration lane and failure-memory interaction when relevant
   - run evidence measurement, management, and judgment interaction when relevant
8. Do not start work from memory alone.

## Project-Specific Guardrails

- This repo is a `concept-preserving reboot`, not a legacy continuation.
- `legacy` findings are `prior evidence only` unless a v2 artifact closes the same question.
- v2 inherits the legacy exploration mandate, not legacy code, run results, winners, or promotion history.
- `Stage 00` is closed as planning scaffold complete.
- derive the current active stage from `docs/workspace/workspace_state.yaml` and active stage docs; do not hard-code the stage name in this skill
- registered architecture debt is not a normal pattern to copy into later stages
- promotion-ineligible does not mean idea-dead
- negative does not mean invalid, and inconclusive does not mean quiet approval
- Long path retries are evidence discovery guardrails only; they do not relax gates, thresholds, MT5 output requirements, or claim boundaries.
