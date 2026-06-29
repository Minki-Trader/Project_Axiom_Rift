---
name: obsidian-runtime-parity
description: Check that Python research, packaged artifacts, MT5 EA behavior, Strategy Tester behavior, and live-like runtime handoff carry the same meaning before runtime claims are made.
---

# Obsidian Runtime Parity

Use this skill when work touches MT5, EA modules, runtime packages, model bundles, `.set` files, tester output, handoff files, live-like execution, or comparisons between Python and runtime behavior.

## Required Output

- `research_path`: Python script, model builder, feature calculator, or report path
- `runtime_path`: MT5 EA, include module, package, `.set`, tester profile, or handoff path
- `shared_contract`: features, labels, inputs, outputs, thresholds, and time-axis rules that must match
- `known_differences`: differences that are intentional or unresolved
- `parity_check`: compile, snapshot, file handoff, tester output, row-level comparison, or reason unavailable
- `parity_identity`: module hashes, bundle hash, parameter hash, tester identity, and output path when applicable
- `runtime_evidence_identity`: dataset_id, feature_set_id, label_id, split_id, ONNX hash, EA source/binary hash, set/ini hash, feature_order_hash, tester identity, report/trade-list/telemetry hash(데이터셋 ID/피처 묶음 ID/라벨 ID/분할 ID/온엑스 해시/EA 원천·실행파일 해시/설정 해시/피처 순서 해시/테스터 정체성/보고서·거래목록·텔레메트리 해시)
- `runtime_learning_probe_decision`: pre_gate_signal_count, strong_candidate_count, runtime_learning_probe_candidate_count, runtime_surface_status, mt5_action, not_run_reason_code, repair_attempt_required, repair_attempts, forbidden_skip_basis_seen, claim_effect(사전 게이트 신호 수/강한 후보 수/런타임 학습 탐침 후보 수/런타임 표면 상태/MT5 행동/미실행 사유 코드/수리 시도 필요 여부/수리 시도/금지 생략 근거/주장 효과)
- `mt5_runtime_probe_contract`: probe_profile(탐침 프로필), validation_is/oos period(검증 내부/표본외 기간), `/portable` execution(포터블 실행), tester setting(테스터 설정), completed report coverage(완료 보고서 커버리지), claim_effect(주장 효과)
- `runtime_claim_boundary`: research-only, runtime_probe, runtime_authority_candidate, blocked, or not_applicable

## Guardrails

- Do not treat Python success as runtime authority.
- Do not treat MetaEditor compile as a substitute for tester or runtime output.
- When runtime/materialization/handoff/economics claims(런타임/물질화/인계/경제성 주장) are protected, prefer the narrow sufficient runtime_probe(좁고 충분한 런타임 탐침) over procedural expansion/advisory loops/deferred checkpoints(절차 확장/자문 반복/지연 점검).
- Do not skip runtime_probe(런타임 탐침) because it is costly/expensive(비용이 듦). Attempt it in the same packet(같은 묶음), or after a recovery attempt(복구 시도) lower `runtime_claim_boundary(런타임 주장 경계)` to blocked, inconclusive, or out_of_scope_by_claim(차단/불충분/주장 범위 밖).
- Do not skip runtime_learning_probe(런타임 학습 탐침) because proxy_bad/candidate_gate_failed/not_strong_candidate/low_trade_count_expected/long_short_imbalanced/cost_expensive(프록시 부진/후보 게이트 실패/강한 후보 아님/거래 수 부족 예상/롱숏 비대칭/비용). If no_actionable_runtime_surface(실행 가능한 런타임 표면 없음) is found, require at least one repair_attempt(수리 시도) before blocked/inconclusive(차단/불충분).
- Standard runtime_probe(표준 런타임 탐침)는 `foundation/config/mt5_runtime_probe_contract.yaml`의 validation_is(검증 내부) `2025.01.02 -> 2025.10.01`과 oos(표본외) `2025.10.01 -> 2026.06.18` 쌍을 사용한다. `runtime_probe_completed(런타임 탐침 완료)`는 두 split(분할)과 completed Strategy Tester report(완료 전략 테스터 보고서)가 모두 있어야 한다.
- Specific period/debug/smoke/regime/source replay(특정 기간/디버그/스모크/장세/원천 재현)는 exception profile(예외 프로필)로만 기록하고, runtime_probe_completed/runtime authority/economics pass(런타임 탐침 완료/런타임 권위/경제성 통과)를 만들지 않는다.
- Strategy Tester execution(전략 테스터 실행)은 `run_mt5_tester(MT5 테스터 실행)`와 `/portable(포터블 모드)`를 사용한다. missing report(보고서 누락)는 success/completion reason(성공/완료 사유)이 아니라 contract audit blocker(계약 감사 차단 사유)다.
- Do not change EA entrypoints for parameter-only experiments.
- Do not hide runtime differences in file names; record identities and hashes.
- On Windows deep stage/MT5 artifact paths, do not classify a native PowerShell/Python path failure as parity failure, missing evidence, invalid setup, or blocked until repo-relative `rg --files`/`rg` has been attempted. When content, existence, or mechanical CSV/JSON reads are needed, start the first read through `foundation.control_plane.ledger.io_path`, `path_exists`, or a helper built on them instead of `Path.read_text`, `Path.exists`, PowerShell `Get-Content`, `Import-Csv`, or pandas direct paths; record the long-path-safe outcome before judging.
- If PowerShell `Import-Csv`, `Measure-Object`, or recursive `Get-ChildItem` reports `Could not find a part of the path` on a known-deep frontier artifact, stop repeating that cmdlet; use `cmd /c dir /x` only to discover a local 8.3 short path, or read through `foundation.control_plane.ledger.io_path` in Python, while preserving repo-relative paths in reports.
