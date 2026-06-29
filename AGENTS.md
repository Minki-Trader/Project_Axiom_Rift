# AGENTS

schema: axiom_rift_agent_rules_v1
project_id: project_axiom_rift
audience: codex_only
human_friendly_text_policy: chat_only
active_text_encoding: ascii_only

## Boot

Read order for any new session or compacted context:

1. `AGENTS.md`
2. `docs/workspace/reentry.yaml`
3. `docs/workspace/workspace_state.yaml`
4. Active stage brief only when stage work is requested.
5. Active contracts only when the task touches their surface.

Do not read archive files during boot.

## Hard Boundaries

- Active project files must be machine-oriented and ASCII-only.
- Human-friendly Korean explanations belong in chat, not project files.
- Archive files are legacy references, not active truth.
- No old winner, selected baseline, promotion, runtime authority, or live-readiness claim is inherited.
- No label, feature set, model family, objective, or trade shape is frozen at restart.
- Claims must be no stronger than current evidence in `docs/workspace/workspace_state.yaml`.

## Current Active Truth

- Active contracts live in `docs/contracts/`.
- Active config lives in `foundation/config/`.
- Current state lives in `docs/workspace/workspace_state.yaml`.
- Reentry summary lives in `docs/workspace/reentry.yaml`.
- Active stage is declared by `active_stage` in `docs/workspace/workspace_state.yaml`.

If active contracts/config are missing, do not substitute archive files as active truth.

## Archive Rule

Legacy archives:

- `archive/imported_fpmarkets_v2_delete_after_axiom_contracts/`
- `archive/imported_obsidian_v2_skills_delete_after_axiom_skills/`

Archive role:

- temporary reference only
- delete after the matching active Axiom Rift contract or skill set is complete
- may contain non-ASCII legacy text
- do not edit unless user explicitly asks
- do not cite as active contract, config, skill, or agent

Official Axiom skills do not exist yet. Legacy Obsidian skills may be inspected only when designing
new ASCII-only Axiom skills.

## Research Mode

Axiom Rift uses autonomous discovery until explicit freeze:

- labels: exploration variables
- features: exploration variables
- model families: exploration variables
- objectives: exploration variables
- trade shapes: exploration variables

Freeze requires an active Axiom Rift contract or decision record with:

- dataset identity
- split boundaries
- feature/order hash when applicable
- artifact identity/hash when applicable
- claim boundary

## Market Defaults

- broker: FPMarkets
- symbol: US100
- timeframe: M5
- base_frame: US100 closed M5 bars
- external_alignment: own closed M5 series merged to US100 close timestamp
- leakage_policy: no_future_leakage

## Placement

- contracts: `docs/contracts/`
- state: `docs/workspace/`
- policies: `docs/policies/`
- raw data: `data/raw/`
- processed reusable data: `data/processed/`
- reusable collectors: `foundation/collectors/`
- reusable features: `foundation/features/`
- reusable pipelines: `foundation/pipelines/`
- active config: `foundation/config/`
- stage work: `stages/<stage_id>/`
- tests: `tests/`

Do not create top-level scratch, notes, scripts, or experiment folders.

## Stage Layout

Every stage uses:

- `00_spec/`
- `01_inputs/`
- `02_runs/active/`
- `02_runs/archived/`
- `03_reviews/`
- `04_selected/`

Do not put raw data in stage folders.
Do not dump run artifacts directly in a stage root.

## Runtime Claims

Runtime/economics/materialization/handoff/live claims require active Axiom Rift runtime contracts
and completed evidence. Compile-only, preview rows, score samples, proxy samples, diagnostic samples,
or archived FPMarkets v2 configs are not enough.

## Filesystem

- Prefer `rg --files` and targeted `rg` for discovery.
- Avoid wide recursive PowerShell scans on deep stage/output trees.
- If deep paths fail, use long-path-aware helpers or `\\?\` only as local execution plumbing.
- Record durable artifact identity as repo-relative paths plus hashes, not local helper prefixes.

## Editing

- Keep active docs concise.
- Prefer YAML/CSV/JSON/short Markdown tables over narrative prose.
- Keep project files ASCII unless a binary/source format requires otherwise.
- Do not add bilingual glossaries to project files.
- Chat can be Korean and user-friendly.
