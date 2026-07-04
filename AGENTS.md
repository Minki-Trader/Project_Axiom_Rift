# AGENTS

schema: axiom_rift_agent_rules_v2
project_id: project_axiom_rift
audience: codex_only
human_friendly_text_policy: chat_only
active_text_encoding: ascii_only

## Boot

Read order for any new session or compacted context:

1. `AGENTS.md`
2. `registries/reentry.yaml`
3. `registries/claim_state.yaml`
4. Active campaign manifest only when campaign work is requested.
5. Active contracts only when the task touches their surface.

Do not read archive files during boot.

## Goal Operation

For short `/goal` prompts, next-work decisions, campaign/run operation, closeout,
or keep-digging versus close decisions, read:

- `.agents/skills/axiom-goal-campaign-operator/SKILL.md`

Short goals inherit:

- `contracts/project_goal_contract.md`
- `contracts/evaluation_contract.md`
- `contracts/goal_operation_policy.yaml`

Top-level target:

- FPMarkets US100 M5.
- Approximately 5 to 10 entries per active trading day.
- Controlled monthly drawdown.
- Strong profitability after realistic spread and slippage.
- EA and ONNX-ready pre-live handoff only.

Failures are assets. Record negative memory, parity lessons, execution divergence
lessons, evidence gaps, or non-portable lessons instead of erasing failed work.

## Hard Boundaries

- Active project files must be machine-oriented and ASCII-only.
- Human-friendly Korean explanations belong in chat, not project files.
- Archive files are legacy references, not active truth.
- No old winner, selected baseline, promotion, runtime authority, or live-readiness claim is inherited.
- No label, feature set, model family, objective, or trade shape is frozen at restart.
- Claims must be no stronger than current evidence in `registries/claim_state.yaml`.
- Short goal prompts do not weaken contracts, claim boundaries, or MT5 evidence rules.
- Adjacent tuning, threshold nudges, window nudges, SL/TP nudges, or retry-only work must not be disguised as new runs.
- Weak proxy results must not skip MT5 paired validation.
- Code that does not run is a repair or blocker surface, not hypothesis evidence.
- Do not record broken code as a completed failure and stop. First triage, repair in scope, rerun, and only then record evidence.
- If broken code cannot be repaired in the current turn, record a blocker with root cause, reproduction command, failing artifact path, next concrete repair step, and the user or external state required.
- Missing KPI caused by broken code, parser failure, compile failure, or runner failure must not close a run, campaign, or goal.
- Every run closeout must be reflected on local `main` and pushed to `origin/main` after validation.
- Do not report a run closeout as operationally complete when the closeout changes remain local only.
- Do not force-push, reset, or discard unrelated work to satisfy run closeout git sync.

## Current Active Truth

- Active contracts live in `contracts/`.
- Active config lives in `configs/`.
- Current claim state lives in `registries/claim_state.yaml`.
- Reentry summary lives in `registries/reentry.yaml`.
- Campaign work lives in `campaigns/`.
- Source code lives in `src/axiom_rift/`.

If active contracts/config are missing, do not substitute archive files as active truth.

## Operational Baselines

- `configs/runtime.yaml` is the active MT5 runner baseline for local terminal,
  account, symbol, timeframe, tester model, and execution defaults. It does not
  create runtime authority, promotion, ONNX, or live-readiness claims.
- Before choosing next work, closing a run/campaign, or trusting registry state,
  use `python -m axiom_rift.cli validate-repo-state` as the repository state check.
  Existing blockers must be reported separately from the current task's changes.
- Data baseline refresh order is `python -m axiom_rift.cli build-us100-base-frame`,
  then `python -m axiom_rift.cli derive-us100-clean-periods`, then
  `python -m axiom_rift.cli build-us100-rolling-windows`.
- `price_quality` and `market_calendar` outputs are data-quality guardrails. They
  do not freeze labels, features, models, split boundaries, runtime authority, or
  live readiness.

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

Official Axiom skills are not complete yet.

Bootstrap-only Axiom skills may exist under `.agents/skills/` as temporary local planning aids.
They are not evidence that `axiom_skills_complete` is true, and they must not create runtime,
promotion, ONNX, or live-readiness claims.

Legacy Obsidian skills may be inspected only when designing new ASCII-only Axiom skills.

## Research Mode

Axiom Rift uses autonomous discovery until explicit freeze:

- labels: exploration variables
- features: exploration variables
- model families: exploration variables
- objectives: exploration variables
- trade shapes: exploration variables

Feature count, feature families, model family, model count, ensembles, direction-specific models,
score surfaces, filters, and exit models remain unrestricted exploration variables until an
active contract or decision record freezes them with evidence.

Early discovery uses fixed-lot evaluation by default. Equity-percent sizing is deferred to later
robustness or growth validation after candidate quality is established; exact sizing rules are
not frozen.

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

- source package: `src/axiom_rift/`
- contracts: `contracts/`
- config: `configs/`
- registries: `registries/`
- raw data: `data/raw/`
- processed reusable data: `data/processed/`
- reusable artifacts: `artifacts/`
- campaign work: `campaigns/<campaign_id>/`
- tests: `tests/`

Do not create top-level scratch, notes, scripts, experiment, or stage folders.

## Campaign Layout

Every campaign uses:

- `campaign.yaml`
- `inputs.yaml`
- `runs/<run_id>/`
- `selected.yaml`

Synthesis work units under `campaigns/SC0001_short_slug/` use:

- `synthesis.yaml`
- `ingredient_refs.yaml`
- `synthesis_queue.yaml`
- `runs/<synthesis_run_id>/`
- `selected.yaml`

Optional synthesis queue mirrors may use:

- `ingredients.csv`
- `ingredients.json`
- `synthesis_queue.csv`
- `synthesis_queue.json`

Do not put raw data in campaign folders.
Do not dump run artifacts directly in a campaign root.
Record durable artifact identity as repo-relative paths plus hashes.

## Runtime Claims

Runtime/economics/materialization/handoff/live claims require active Axiom Rift runtime contracts
and completed evidence. Compile-only, preview rows, score samples, proxy samples, diagnostic samples,
or archived FPMarkets v2 configs are not enough.

## MT5 Validation Guardrails

For any task touching MT5 EAs, MQH include modules, MQL5 scripts, tester configs, MT5 KPI parsers,
proxy-vs-MT5 parity, execution-divergence evidence, or MT5-generated campaign evidence, read:

- `.agents/skills/axiom-mt5-validation-guardrails/SKILL.md`

Rules:

- Opened runs are not proxy-only scouts.
- Proxy KPI is a reference surface and must not be used as a go/no-go gate for MT5.
- Weak, losing, or ugly proxy results must not skip MT5 logic parity, MT5 tick KPI, execution divergence, or fold-isolated closeout evidence.
- Use closed-bar OHLC MT5 runs for proxy-vs-EA logic parity.
- Use tick-mode MT5 runs for actual execution KPI management.
- Record tick-vs-closed-bar differences as execution divergence, not as automatic logic failure.
- Treat aggregate full-period MT5 KPI as diagnostic only for run closeout.
- Require rolling-window fold-isolated MT5 tick KPI and fold-isolated execution divergence before run closeout, unless a complete exception is recorded.
- Keep reusable EA, MQH, script, runner, parser, and proxy components in stable project source paths.
- Do not rewrite shared/reusable EA, runner, parser, MQH, or helper components from scratch when a project source exists.
- Run-specific EAs and variant-specific signal logic may be newly created, but must reuse existing shared helpers instead of copy-pasting or reinventing them.
- Keep EA bodies thin; move reusable MQL logic into MQH includes and parser/ledger logic into Python helpers.
- MT5 compile success is never enough when validation was requested; run or parse evidence and check missing KPI fields.

Placement:

- EA sources: `src/axiom_rift/mt5/experts/`
- MQH include modules: `src/axiom_rift/mt5/include/`
- MQL5 scripts: `src/axiom_rift/mt5/scripts/`
- Python MT5 runners, compilers, and parsers: `src/axiom_rift/mt5/`
- Proxy engines: `src/axiom_rift/proxies/`
- Durable run KPI evidence: `campaigns/<campaign_id>/runs/<run_id>/kpi/`

## Filesystem

- Prefer `rg --files` and targeted `rg` for discovery.
- Avoid wide recursive PowerShell scans on deep output trees.
- If deep paths fail, use long-path-aware helpers or `\\?\` only as local execution plumbing.
- Record durable artifact identity as repo-relative paths plus hashes, not local helper prefixes.

## Editing

- Keep active docs concise.
- Prefer YAML/CSV/JSON/JSONL over narrative prose.
- Keep project files ASCII unless a binary/source format requires otherwise.
- Do not add bilingual glossaries to project files.
- Chat can be Korean and user-friendly.
