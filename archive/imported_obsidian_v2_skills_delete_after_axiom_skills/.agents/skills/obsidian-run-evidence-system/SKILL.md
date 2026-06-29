---
name: obsidian-run-evidence-system
description: Manage Project Obsidian Prime v2 run evidence across KPI measurement, run result identity, EA/MT5 tester identity, and lane-aware judgment. Use for run creation, run closeout, KPI reports, result summaries, stage run reviews, run registry updates, EA/MT5 tester runs, or deciding whether a run is positive, negative, inconclusive, or invalid.
---

# Obsidian Run Evidence System

Use this skill when a task creates, reviews, closes, summarizes, or registers run (`실행`) evidence.

## Automatic Bundle

When this skill triggers for run creation(실행 생성), run closeout(실행 종료), KPI report(KPI 보고), result summary(결과 요약), or run registry update(실행 등록부 갱신), pair it with `obsidian-claim-discipline`.

Effect(효과): measurement(측정), identity(정체성), judgment(판정), and registry boundary(등록부 경계) stay explicit before any run is called reviewed(검토됨), selected(선택됨), positive(긍정), negative(부정), inconclusive(불충분), invalid(무효), operating_promotion(운영 승격), or runtime_authority(런타임 권위).

## Must Read

- `docs/policies/kpi_measurement_standard.md`
- `docs/policies/run_result_management.md`
- `docs/policies/result_judgment_policy.md`
- `docs/registers/run_registry.csv`
- `docs/policies/exploration_mandate.md` when the run is exploration-sensitive
- `docs/policies/promotion_policy.md` when promotion is possible
- `docs/policies/tiered_readiness_exploration.md` when Tier A/B/C readiness is involved

## Required Output

- `measurement_scope`: which KPI (`key performance indicator`, 핵심 성과 지표) layers are required
- `management_state`: run folder (`실행 폴더`), manifest, KPI record, summary, and registry state
- `judgment_class`: `positive`, `negative`, `inconclusive`, or `invalid`
- `scoreboard`: `structural_scout`, `regular_risk_execution`, `wfo_oos`, `runtime_parity`, or `diagnostic_special`
- `parity_level`: `P0_unverified`, `P1_dataset_feature_aligned`, `P2_model_input_parity_closed`, `P3_runtime_shadow_parity_sampled`, or `P4_full_runtime_parity_closed`
- `wfo_status`: `not_applicable`, `planned`, `partial`, `complete`, or `exception`
- `registry_update_required`: `yes` or `no`
- `negative_memory_required`: `yes` or `no`
- `hard_gate_applicable`: `yes` only for `operating_promotion` or `runtime_authority`
- `evidence_boundary`: `scout-only`, `candidate`, `probe`, `reviewed`, `selected`, `operating_promotion`, or `runtime_authority`

## EA/MT5 Run Identity(EA/MT5 실행 정체성)

When a run uses MT5 EA(`Expert Advisor`, 전문가 자문), Strategy Tester(전략 테스터), `.set` file(설정 파일), runtime package(런타임 패키지), or model bundle(모델 번들), add the following identity fields to the manifest(목록), KPI record(KPI 기록), or equivalent evidence:

- `ea_entrypoint`: main `.mq5` path(경로) and sha256 hash(해시)
- `ea_variant_boundary`: `parameter_only/module_change/entrypoint_change/new_runner_required(파라미터만/모듈 변경/진입점 변경/새 실행기 필요)`
- `set_file`: `.set` path(설정 파일 경로) and sha256 hash(해시), or explicit `not_applicable(해당 없음)` reason
- `input_params_hash`: canonical input parameter hash(정규 입력 파라미터 해시)
- `module_hashes`: `.mqh` module list(모듈 목록) and sha256 hashes(해시)
- `model_or_bundle_hash`: model/bundle artifact hash(모델/번들 산출물 해시)
- `tester_identity`: symbol(심볼), timeframe(시간프레임), tester model(테스터 모델), deposit(예치금), leverage(레버리지), spread/cost assumption(스프레드/비용 가정)
- `tester_output_path`: terminal output(터미널 출력), tester report(테스터 보고서), or runtime telemetry(런타임 기록) path(경로)

Effect(효과): profit(수익), drawdown(손실 곡선), execution KPI(실행 KPI), runtime probe(런타임 탐침)를 말할 때 어느 EA code(코드), setting(설정), module(모듈), model bundle(모델 번들)에서 나온 결과인지 끊기지 않는다.

## Guardrails

- Early scout runs may use partial evidence if the missing layers and evidence boundary are labeled.
- Do not close a reviewed or selected run without machine-readable KPI evidence or explicit `n/a` reasons.
- Do not confuse `negative` (`부정`) with `invalid` (`무효`).
- Do not treat `inconclusive` (`불충분`) as either success or failure.
- Do not claim `operating_promotion` (`운영 승격`) from `structural_scout` (`구조 탐색 점수판`) or `promotion_candidate` (`승격 후보`) evidence alone.
- Do not claim `runtime_authority` (`런타임 권위`) from `runtime_probe` (`런타임 탐침`) evidence.
- Do not blend Tier B/C research KPI with Tier A promotion or runtime KPI.
- For Tier A primary + Tier B fallback routing(Tier A 우선 + Tier B 대체 라우팅), record Tier A used(Tier A 사용), Tier B fallback used(Tier B 대체 사용), and actual routed total(실제 라우팅 전체); do not present a synthetic sum(합성 합산) of separate tester runs(분리 테스터 실행) as the combined record(합산 기록).
- Do not claim `P4_full_runtime_parity_closed` from lower-level parity evidence.
- Keep large artifacts outside Git only when their identity, path, and hash are represented in Git-tracked evidence.
- Do not mark an EA/MT5 tester run as reviewed if `ea_entrypoint`, `set_file` or equivalent config, `module_hashes`, `model_or_bundle_hash`, and `tester_identity` are missing without explicit `not_applicable(해당 없음)` reasons.

## Closeout Checklist

Before marking a run as reviewed, selected, archived, invalidated, or superseded:

1. Confirm `run_manifest.json` or equivalent identity evidence exists.
2. Confirm `kpi_record.json` or equivalent KPI evidence exists.
3. Confirm `result_summary.md` or equivalent human readout exists.
4. Confirm `docs/registers/run_registry.csv` has or will receive a row.
5. Classify the result as `positive`, `negative`, `inconclusive`, or `invalid`.
6. If the result closes an exploration idea negatively, record salvage value and reopen condition.

Before claiming `operating_promotion` or `runtime_authority`, confirm the relevant hard-gate evidence exists and the claim is backed by a durable decision or closure artifact.
