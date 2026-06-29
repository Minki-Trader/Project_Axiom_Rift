# Training Label Split Contract FPMarkets v2

## 목적(Purpose, 목적)

이 문서는 FPMarkets v2 첫 training dataset(학습 데이터셋)의 label(라벨)과 split(분할) 규칙을 고정한다.

쉽게 말하면, 모델에게 줄 첫 시험지의 정답 기준과 연습/검증/표본외 구간을 정한다.

## 범위(Scope, 범위)

- source dataset(원천 데이터셋): `dataset_fpmarkets_v2_us100_m5_20220901_20260413_cashopen_fullcash_valid_freeze01`
- training dataset(학습 데이터셋): `training_fpmarkets_v2_us100_m5_label_v1_fwd12_m5_logret_train_q33_3class_split_v1`
- feature order hash(피처 순서 해시): `fa06973c24462298ea38d84528b07ca0adf357e506f3bfeea02eb0d5691ab8e2`
- materialized path(물질화 경로): `data/processed/training_datasets/label_v1_fwd12_split_v1/training_dataset.parquet`

## 라벨 정의(Label Definition, 라벨 정의)

`label_v1_fwd12_m5_logret_train_q33_3class`

각 row(행)의 정답은 현재 닫힌 M5 bar(5분 봉)에서 정확히 12개 M5 bar 뒤, 즉 60분 뒤의 `US100` close(종가)로 계산한다.

공식(formula, 공식):

```text
future_log_return_12 = ln(close_at_t_plus_60m / close_at_t)
```

정확한 60분 뒤 raw close(원천 종가)가 없거나, 현재 row(행)가 60분 뒤에도 정규장 안에 머물 수 없으면 라벨 대상에서 제외한다.

효과(effect, 효과): `다음 12개 유효행`이 아니라 실제 60분 뒤 움직임을 맞히게 하므로, 결측 row(행)가 라벨 시간을 바꾸지 못한다.

## 클래스(Class, 분류)

threshold(임계값)는 train split(학습 분할)에서 `abs(future_log_return_12)`의 33% quantile(분위수)로 계산한다.

- threshold_log_return(로그수익률 임계값): `0.001277833051854688`
- `short(하락)`: `future_log_return_12 < -threshold`
- `flat(중립)`: `abs(future_log_return_12) <= threshold`
- `long(상승)`: `future_log_return_12 > threshold`

class id(분류 ID):

- `short(하락)`: `0`
- `flat(중립)`: `1`
- `long(상승)`: `2`

효과(effect, 효과): 첫 기본 모델은 큰 방향성만 배우고, 작은 움직임은 억지 방향 베팅으로 취급하지 않는다.

## 분할 규칙(Split Rule, 분할 규칙)

`split_v1_calendar_train_20220901_20241231_val_20250101_20250930_oos_20251001_20260413`

시간순 분할(time-ordered split, 시간순 분할)을 쓴다. 무작위 섞기(random shuffle, 무작위 섞기)는 쓰지 않는다.

- train(학습): `2022-09-01T00:00:00Z <= timestamp < 2025-01-01T00:00:00Z`
- validation(검증): `2025-01-01T00:00:00Z <= timestamp < 2025-10-01T00:00:00Z`
- OOS(`out-of-sample`, 표본외): `2025-10-01T00:00:00Z <= timestamp <= 2026-04-13T23:55:00Z`

효과(effect, 효과): 모델이 미래 구간을 미리 섞어 배우는 leakage(미래 정보 누수)를 막는다.

## 물질화 결과(Materialized Result, 물질화 결과)

- total rows(전체 행): `46650`
- train rows(학습 행): `29222`
- validation rows(검증 행): `9844`
- OOS rows(표본외 행): `7584`
- excluded rows(제외 행): `7789`

train class distribution(학습 분류 분포):

- short(하락): `9064`
- flat(중립): `9643`
- long(상승): `10515`

validation class distribution(검증 분류 분포):

- short(하락): `2920`
- flat(중립): `3631`
- long(상승): `3293`

OOS class distribution(표본외 분류 분포):

- short(하락): `2259`
- flat(중립): `2968`
- long(상승): `2357`

## 경계(Boundary, 경계)

이 계약(contract, 계약)은 첫 training dataset(학습 데이터셋)을 만들기 위한 기본 채점표다.

아직 다음은 주장하지 않는다.

- model quality(모델 품질)
- alpha quality(알파 품질)
- runtime authority(런타임 권위)
- operating promotion(운영 승격)
- live readiness(실거래 준비)
