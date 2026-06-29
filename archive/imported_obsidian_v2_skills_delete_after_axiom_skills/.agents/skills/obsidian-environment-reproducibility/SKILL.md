---
name: obsidian-environment-reproducibility
description: Keep project work reproducible across clean checkout, dependencies, Python versions, CI, MT5 paths, external artifacts, and local machine assumptions.
---

# Obsidian Environment Reproducibility

Use this skill when work touches tests, README commands, dependency setup, CI, clean checkout behavior, MT5 terminal paths, local absolute paths, external artifacts, or instructions another machine must run.

## Required Output

- `execution_environment`: OS, Python, MT5, broker terminal, or CI context when relevant
- `dependency_surface`: packages, versions, tools, and missing install contract
- `entry_command`: command a clean checkout should run
- `local_assumptions`: absolute paths, terminal data roots, environment variables, or machine-only files
- `clean_checkout_status`: expected to pass, expected blocked, not tested, or not applicable
- `recovery_instruction`: install, configure, fetch artifact, regenerate, or user action
- `reproducibility_judgment`: reproducible, reproducible_with_setup, local_only, inconclusive, or blocked

## Guardrails

- Do not document a test command as default if dependencies are not declared.
- Do not rely on repository location to discover MT5 data roots without a fail-fast check or configuration path.
- Do not describe missing artifacts as reproducible unless fetch or regeneration steps exist.
- On Windows(윈도우) deep stage path(깊은 단계 경로) or MT5 artifact path(MT5 산출물 경로), do not classify(분류) a file as missing(누락) or blocked(차단) after a single native PowerShell/Python path failure(파워셸/파이썬 경로 실패)만으로 판정하지 않는다. Discovery(발견)는 repo-relative path(저장소 상대 경로) `rg --files`/`rg`로 먼저 하고, first content/existence read(첫 내용/존재 읽기) 또는 mechanical CSV/JSON rewrite(기계적 표/제이슨 수정)는 일반 `Path.read_text`, `Path.exists`, `Get-Content`, `Import-Csv`, pandas direct path(판다스 직접 경로)가 아니라 처음부터 `foundation.control_plane.ledger.io_path`/`path_exists`를 거쳐 수행한 뒤 missing(누락)을 기록한다.
- On Windows(윈도우), Python/Grok command(파이썬/그록 명령)가 Korean or Unicode(한국어 또는 유니코드)를 stdout(표준 출력)으로 낼 수 있으면 `$env:PYTHONIOENCODING='utf-8'; $env:PYTHONPATH='.'`를 command prelude(명령 앞 준비)로 둔다. Prompt fidelity(프롬프트 보존)가 중요하면 inline PowerShell here-string(파워셸 here-string)보다 UTF-8 prompt file(UTF-8 프롬프트 파일)과 `--prompt-file`을 우선한다.
- If copied report/template text(복사된 보고서/템플릿 문구)가 mojibake(깨진 문자)로 나타나 `apply_patch` context(패치 문맥)가 맞지 않으면, encoding repair(인코딩 수리)로 분류하고 function-bounded mechanical rewrite(함수 경계 기계 재작성)를 수행한 뒤 `python -m py_compile` and artifact reread(산출물 재읽기)를 한다. Korean `.md`/`.txt` repair(한국어 문서 수리)는 UTF-8 with BOM(UTF-8 BOM 포함)을 유지한다.

Effect(효과): reproducibility notes(재현성 기록)가 real missing artifact(실제 누락 산출물), Windows long-path access failure(윈도우 긴 경로 접근 실패), and console encoding failure(콘솔 인코딩 실패)를 구분하고, 다음 agent(에이전트)에 stable retry recipe(안정 재시도 절차)를 준다. These guards(이 보호 규칙)는 execution environment(실행 환경)만 다루며 gate/threshold/evidence(게이트/임계값/근거)를 완화하지 않는다.
