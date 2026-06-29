# Model Input Feature Set Contract FPMarkets v2

## 목적(Purpose, 목적)

이 계약(contract, 계약)은 Stage 04(4단계)의 model input feature set(모델 입력 피처 세트)을 고정한다.

효과(effect, 효과)는 training dataset(학습 데이터셋)에 남아 있는 임시 feature(임시 피처)나 가중치 의미(weight meaning, 가중치 의미)가 조용히 바뀌지 않게 하는 것이다.

## 원천(Source, 원천)

초기 원천(source, 원천):

- source training dataset(원천 학습 데이터셋): `training_fpmarkets_v2_us100_m5_label_v1_fwd12_m5_logret_train_q33_3class_split_v1`
- source path(원천 경로): `data/processed/training_datasets/label_v1_fwd12_split_v1/training_dataset.parquet`
- source feature count(원천 피처 수): `58`
- source feature order hash(원천 피처 순서 해시): `fa06973c24462298ea38d84528b07ca0adf357e506f3bfeea02eb0d5691ab8e2`

선택된 원천(selected source, 선택 원천):

- source training dataset(원천 학습 데이터셋): `training_fpmarkets_v2_us100_m5_label_v1_fwd12_split_v1_proxyw58`
- source path(원천 경로): `data/processed/training_datasets/label_v1_fwd12_split_v1_proxyw58/training_dataset.parquet`
- source feature count(원천 피처 수): `58`
- source feature order hash(원천 피처 순서 해시): `fa06973c24462298ea38d84528b07ca0adf357e506f3bfeea02eb0d5691ab8e2`

## 임시 Feature Set(임시 피처 세트)

- feature_set_id(피처 세트 ID): `feature_set_v1_no_placeholder_top3_weight_features`
- model_input_dataset_id(모델 입력 데이터셋 ID): `model_input_fpmarkets_v2_us100_m5_label_v1_fwd12_split_v1_feature_set_v1_no_placeholder_top3_weights`
- included feature count(포함 피처 수): `56`
- included feature order hash(포함 피처 순서 해시): `84f313815393429acb9690d727b61b4a3dfd2354678bd357a53db570ba37bc89`

다음 feature(피처)는 임시 model input(모델 입력)에서 제외했다.

- `top3_weighted_return_1`
- `us100_minus_top3_weighted_return_1`

이유(reason, 이유)는 이 시점의 top3 weight source(top3 가중치 원천)가 `placeholder_equal_weight(임시 동일가중)` 상태였기 때문이다.

효과(effect, 효과)는 임시 동일가중 가정이 조용히 첫 모델 입력에 섞이지 않게 한 것이다.

## 선택된 58 Feature Set(선택된 58개 피처 세트)

- feature_set_id(피처 세트 ID): `feature_set_v2_mt5_price_proxy_top3_weights_58_features`
- model_input_dataset_id(모델 입력 데이터셋 ID): `model_input_fpmarkets_v2_us100_m5_label_v1_fwd12_split_v1_proxyw58_feature_set_v2`
- output path(출력 경로): `data/processed/model_inputs/label_v1_fwd12_split_v1_feature_set_v2_mt5_price_proxy_58/model_input_dataset.parquet`
- included feature count(포함 피처 수): `58`
- included feature order hash(포함 피처 순서 해시): `fa06973c24462298ea38d84528b07ca0adf357e506f3bfeea02eb0d5691ab8e2`
- restored features(복구 피처): `top3_weighted_return_1`, `us100_minus_top3_weighted_return_1`

가중치 원천(weight source, 가중치 원천):

- contract(계약): `docs/contracts/top3_price_proxy_weight_contract_fpmarkets_v2.md`
- table(표): `foundation/config/top3_monthly_price_proxy_weights_fpmarkets_v2.csv`
- method(방법): `mt5_price_proxy_close_share_v1`
- month coverage(월별 범위): `2022-08`~`2026-04`
- bootstrap month(초기 월): `2022-08`

효과(effect, 효과)는 placeholder weight(임시 가중치) 없이 58 feature(58개 피처) model input(모델 입력)을 닫는 것이다.

## 경계(Boundary, 경계)

선택된 58 feature set(58개 피처 세트)은 MT5 price-proxy monthly top3 weights(MT5 가격 대리 월별 top3 가중치)를 쓴다.

이 가중치는 actual NDX/QQQ weights(실제 NDX/QQQ 가중치), QQQ holdings weights(QQQ 보유비중), market cap(시가총액), float(유동주식수)를 반영하지 않는다.

따라서 이 계약(contract, 계약)은 model-input readiness evidence(모델 입력 준비 근거)만 닫는다.

이 계약(contract, 계약)은 MT5 input order contract(MT5 입력 순서 계약)를 닫지 않는다. Python/MT5 feature parity(파이썬/MT5 피처 동등성)는 Stage 06(6단계)에서 확인한다.

아직 model training result(모델 학습 결과), alpha quality(알파 품질), runtime authority(런타임 권위), operating promotion(운영 승격)을 주장하지 않는다.
