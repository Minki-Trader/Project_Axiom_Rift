# Python Feature Parser Spec FPMarkets v2

## 1. 문서 목적

이 문서는 Python 전처리 파이프라인이 원시 시세 데이터를 받아 **모델 입력용 feature row**를 생성하는 절차 계약을 고정한다.  
이 문서는 다음 문서의 하위 실행 규격이다.

- `feature_calculation_spec_fpmarkets_v2.md`: 각 feature의 의미와 계산식
- `mt5_ea_input_order_contract_fpmarkets_v2.md`: MT5 EA 런타임에서의 동일 입력 순서 계약

핵심 목표는 아래 세 가지다.

1. 학습 데이터 생성과 실전 추론 입력이 **동일 의미**를 갖도록 한다.
2. Python ↔ MT5 간 feature drift를 방지한다.
3. 입력 컬럼 순서, warmup, 결측 처리, 외부 심볼 정렬 방식을 재현 가능하게 고정한다.

---

## 2. 범위와 비범위

### 2.1 범위
이 문서는 아래를 포함한다.

- 원시 데이터 입력 계약
- 시계열 정렬 규칙
- 확정봉 기준 규칙
- feature 계산 절차 순서
- 외부 심볼 merge 규칙
- warmup / NaN / invalid-row 규칙
- 최종 DataFrame 컬럼 순서
- 학습용 export 규칙

### 2.2 비범위
이 문서는 아래를 포함하지 않는다.

- 라벨 정의
- 모델 구조
- 하이퍼파라미터 탐색
- threshold 최적화
- 주문 실행 로직
- 리스크 관리 정책

---

## 3. 상위 원칙

### 3.1 closed-bar only
모든 feature는 **가장 최근에 확정된 bar**를 기준으로 계산한다.  
현재 진행 중인 bar의 값은 사용 금지다.

### 3.2 no future leakage
어떤 단계에서도 미래 시점의 값, 미래 bar, 미래 세션 정보, 미래 merge 결과를 사용하면 안 된다.

### 3.3 parser output is deterministic
동일 입력 데이터와 동일 파서 버전이면 동일 feature matrix가 생성되어야 한다.

### 3.4 feature order is frozen
최종 출력 컬럼 순서는 본 문서 11장의 순서를 따른다.  
순서 변경은 **새 계약 버전**이 필요하다.

### 3.5 parser computes raw features
FPMarkets v2 parser는 **raw feature**를 산출한다.  
표준화/스케일링/정규화는 모델 전처리 단계에서 별도로 다룬다.  
스케일링이 필요하면 IS 구간에서만 fit하고, 파라미터를 별도 artifact로 고정해야 한다.

---

## 4. 입력 데이터 계약

### 4.1 메인 심볼 데이터
주 대상은 `US100`, timeframe은 `M5`.

필수 컬럼:

- `timestamp`
- `open`
- `high`
- `low`
- `close`

선택 컬럼:

- `spread`
- `symbol`
- `source`

주의:

- `tick_volume`, `real_volume`, `volume`은 FPMarkets v2 필수 입력이 아니다.
- 모든 row는 **bar close timestamp** 기준으로 해석한다.
- 메인 시계열에는 중복 timestamp가 있으면 안 된다.
- timestamp는 monotonic increasing이어야 한다.

### 4.2 외부 시리즈 데이터
외부 시리즈는 아래 범주를 포함할 수 있다.

- risk proxies: `VIX`, `US10YR`, `USDX`
- leader stocks: `NVDA`, `AAPL`, `MSFT`, `AMZN`
- breadth basket constituents: `AAPL`, `AMZN`, `AMD`, `GOOGL`, `META`, `MSFT`, `NVDA`, `TSLA`

필수 컬럼:

- `timestamp`
- `close`

선택 컬럼:

- `open`
- `high`
- `low`
- `source`
- `symbol`

### 4.3 timezone contract
- 시간축 정책(time-axis policy, 시간축 정책)은 `docs/contracts/time_axis_policy_fpmarkets_v2.md`를 따른다.
- 원천 `time_open_unix`와 `time_close_unix`는 직접 UTC(direct UTC, 직접 협정세계시)가 아니라 브로커 시계 정렬 키(broker-clock alignment key, 브로커 시계 정렬 키)로 취급한다.
- 외부 심볼 정렬(external symbol alignment, 외부 심볼 정렬)은 같은 브로커 시계 닫힘 키(broker-clock close key, 브로커 시계 닫힘 키)를 기준으로 한다.
- session feature(세션 피처) 계산은 검증된 `timestamp_event_utc(이벤트 UTC 타임스탬프)`와 `timestamp_ny(뉴욕 타임스탬프)`, 또는 명시적으로 검증된 브로커 세션 달력(broker session calendar, 브로커 세션 달력)이 있을 때만 닫힌 것으로 본다.
- 원천 브로커 시계 키(raw broker-clock key, 원천 브로커 시계 키)에 직접 `tz_convert("America/New_York")`를 적용하는 방식은 feature-frame closure(피처 프레임 폐쇄) 근거가 아니다.

---

## 5. 전처리 절차

### 5.1 타입 정규화
- `timestamp`를 timezone-aware datetime으로 강제 변환한다.
- 가격 컬럼은 float64로 변환한다.
- `high < low` 또는 비정상 OHLC row는 invalid 처리한다.

### 5.2 정렬 및 중복 제거
- `timestamp` 기준 오름차순 정렬
- 같은 timestamp 중복 row 존재 시 즉시 에러 또는 사전 정의된 dedup 정책 적용
- 권장 기본값: 중복은 침묵 처리하지 말고 실패시킨다

### 5.3 closed-bar filter
실시간 수집 데이터에 미완성 bar가 섞여 있으면 제거한다.  
학습 데이터셋은 **확정봉만 포함**해야 한다.

### 5.4 bar continuity audit
- M5 기준 row 간격은 원칙적으로 5분이다.
- 주말/휴장/비거래 시간 공백은 허용된다.
- 그러나 비정상적인 intra-session missing hole은 로그에 남긴다.

---

## 6. Python 파서 단계별 처리 순서

권장 순서는 반드시 아래를 따른다.

### Step 1. Base frame 생성
메인 심볼 OHLC로 기준 DataFrame 생성.

### Step 2. primitive series 계산
다음 primitive를 먼저 계산한다.

- simple return series
- log return series
- rolling mean / rolling std
- EMA / SMA
- ATR
- RSI
- Bollinger primitives
- Keltner primitives
- stochastic primitives
- ADX / DI primitives
- realized volatility primitives

### Step 3. 메인 심볼 feature 계산
`feature_calculation_spec_fpmarkets_v2.md`에 정의된 메인 심볼 feature를 계산한다.

### Step 4. session feature 계산
검증된 `timestamp_ny(뉴욕 타임스탬프)` 또는 브로커 세션 달력(broker session calendar, 브로커 세션 달력) 기준으로 다음을 계산한다.

- `is_us_cash_open`
- `minutes_from_cash_open`
- `is_first_30m_after_open`
- `is_last_30m_before_cash_close`
- `overnight_return`

### Step 5. 외부 시리즈 전처리
각 외부 시리즈에 대해:

1. timestamp 정규화
2. close series 확보
3. bar-close 기준 정렬
4. 필요 feature 계산
5. 메인 프레임에 merge

### Step 6. breadth / aggregate feature 계산
외부 constituent가 모두 준비된 후 아래를 계산한다.

- `mega8_equal_return_1`
- `top3_weighted_return_1`
- `mega8_pos_breadth_1`
- `mega8_dispersion_5`
- `us100_minus_mega8_equal_return_1`
- `us100_minus_top3_weighted_return_1`

### Step 7. 최종 feature order 정렬
11장에 정의된 frozen order로 컬럼 재정렬.

### Step 8. row validity mask 생성
결측/정렬 실패/warmup 부족 row를 걸러낸다.

### Step 9. export
최종 결과를 dataset 또는 inference snapshot용 포맷으로 저장한다.

---

## 7. 외부 심볼 merge 규칙

### 7.1 기본 원칙
외부 시리즈는 **동일 bar-close timestamp** 기준으로만 정렬한다.

### 7.2 금지 사항
금지:

- 미래값 backward fill
- exchange/session boundary를 넘는 forward fill
- NY 현물 종목 휴장 구간을 CFD 연속 시계열로 억지 보간
- bar open 기준 혼용

### 7.3 허용 가능한 예외
같은 거래 세션 안에서, 동일 provider가 이미 bar-close 기준으로 안정적으로 resample한 데이터를 제공하고 있고, 사전 승인된 규칙이 문서화된 경우에만 제한적으로 허용한다.  
그러나 FPMarkets v2 기본값은 **same timestamp exact match only**다.

### 7.4 invalid-row rule
필수 외부 feature 중 하나라도 해당 timestamp에 존재하지 않으면 그 row는 **모델 입력 불가**다.

---

## 8. warmup 및 NaN 정책

### 8.1 warmup minimum
가장 긴 내부 lookback과 smoothing 안정화를 고려해, FPMarkets v2 parser는 최소 **300 bars warmup**을 권장한다.

이유:

- `ema50_ema200_diff`
- `sma50_sma200_ratio`
- `hl_zscore_50`
- `historical_vol_20`
- 각종 누적 smoothing indicator

### 8.2 feature-level NaN
공식적으로 warmup 미충족인 feature는 `NaN`으로 둔다.

### 8.3 row-level validity
학습용 최종 matrix에서는 아래 중 하나라도 참이면 row를 제거한다.

- required feature NaN
- required external series missing
- session timestamp 변환 실패
- duplicate timestamp contamination
- divide-by-zero rule violation after contract fallback is applied

### 8.4 divide-by-zero fallback
`feature_calculation_spec_fpmarkets_v2.md`에 따라 rolling std가 0이면 z-score는 `0.0`으로 강제한다.  
그 외 ratio 분모가 0 또는 비정상값이면 row invalid 처리한다.

---

## 9. 세션 계산 규칙

### 9.1 기준 세션
미국 core cash session = 09:30 ~ 16:00, timezone = `America/New_York`

### 9.2 bar timestamp interpretation
세션 feature는 **bar close timestamp** 기준으로 계산한다.

예:

- 09:35 close → `minutes_from_cash_open = 5`
- 16:00 close → cash session 마지막 close로 취급 가능

### 9.3 overnight_return
`overnight_return`은 아래로 계산한다.

- 당일 NY cash 첫 bar open
- 직전 유효 NY trading session의 마지막 cash close

그리고 같은 NY trading date 안에서만 forward-fill 한다.

---

## 10. scaling / normalization 정책

### 10.1 기본 정책
parser FPMarkets v2 자체는 scaling을 수행하지 않는다.

### 10.2 예외
모델이 scaler 내장 ONNX graph를 사용하는 경우, parser 출력은 여전히 raw order를 유지하고, scaler는 모델 artifact 일부로 취급한다.

### 10.3 금지
- full sample 전체로 scaler fit
- OOS 정보를 포함한 fit
- feature order가 다른 상태에서 scaler 재사용

---

## 11. Frozen output column order

최종 출력 컬럼 순서는 정확히 아래와 같다.

```text
00. log_return_1
01. log_return_3
02. hl_range
03. close_open_ratio
04. gap_percent
05. close_prev_close_ratio
06. return_zscore_20
07. hl_zscore_50
08. overnight_return
09. return_1_over_atr_14
10. close_ema20_ratio
11. close_ema50_ratio
12. ema9_ema20_diff
13. ema20_ema50_diff
14. ema50_ema200_diff
15. ema20_ema50_spread_zscore_50
16. sma50_sma200_ratio
17. rsi_14
18. rsi_50
19. rsi_14_slope_3
20. rsi_14_minus_50
21. stoch_kd_diff
22. stochrsi_kd_diff
23. ppo_hist_12_26_9
24. roc_12
25. trix_15
26. atr_14
27. atr_50
28. atr_14_over_atr_50
29. bollinger_width_20
30. bb_position_20
31. bb_squeeze
32. historical_vol_20
33. historical_vol_5_over_20
34. adx_14
35. di_spread_14
36. supertrend_10_3
37. vortex_indicator
38. is_us_cash_open
39. minutes_from_cash_open
40. is_first_30m_after_open
41. is_last_30m_before_cash_close
42. vix_change_1
43. vix_zscore_20
44. us10yr_change_1
45. us10yr_zscore_20
46. usdx_change_1
47. usdx_zscore_20
48. nvda_xnas_log_return_1
49. aapl_xnas_log_return_1
50. msft_xnas_log_return_1
51. amzn_xnas_log_return_1
52. mega8_equal_return_1
53. top3_weighted_return_1
54. mega8_pos_breadth_1
55. mega8_dispersion_5
56. us100_minus_mega8_equal_return_1
57. us100_minus_top3_weighted_return_1
```

총 feature 수: **58**

---

## 12. 출력 스키마

### 12.1 training dataset minimum columns
권장 최소 출력:

- `timestamp`
- `symbol`
- `log_return_1` ~ `us100_minus_top3_weighted_return_1`
- optional labels (별도 문서 기준)
- optional row validity flags

### 12.2 inference snapshot minimum columns
권장 최소 출력:

- `timestamp`
- `feature_vector`
- `feature_order_version`
- `parser_version`
- `source_snapshot_id`

### 12.3 dtype
권장 dtype:

- feature columns: `float32` 또는 export 직전 `float32` cast
- audit/debug intermediate: `float64` 허용

권장 실무 흐름:

- 내부 계산: float64
- 최종 export / ONNX 직전: float32

---

## 13. 권장 함수 책임 분리

권장 모듈 책임은 다음과 같다.

- `load_main_symbol_data()`
- `load_external_series()`
- `normalize_timestamps()`
- `compute_base_primitives()`
- `compute_main_symbol_features()`
- `compute_session_features()`
- `compute_external_features()`
- `compute_breadth_features()`
- `apply_row_validity_mask()`
- `freeze_feature_order()`
- `export_feature_matrix()`

핵심은 **계산 책임**과 **정렬 책임**을 분리하는 것이다.

---

## 14. 최소 검증 규칙

파서 완료 후 아래를 반드시 검증한다.

1. feature column 개수 = 58
2. output column 순서가 11장과 정확히 일치
3. timestamp unique = true
4. timestamp monotonic increasing = true
5. required feature NaN 비율 확인
6. 외부 시리즈 미스매치 row 수 로그
7. DST 전환 주간에서 세션 feature sanity check
8. `overnight_return`이 하루에 한 번만 바뀌는지 확인
9. Python vs MT5 parity sample 비교 가능하도록 snapshot 저장

---

## 15. 파서 실패 시 처리 원칙

- 조용히 보정하지 않는다.
- 애매한 자동 수정은 하지 않는다.
- invalid row를 억지로 살리지 않는다.
- merge mismatch는 반드시 로그로 남긴다.
- feature drift 의심 시 즉시 artifact 버전을 올린다.

---

## 16. 권장 산출물

파서 1회 실행 시 아래 산출물을 함께 남기는 것을 권장한다.

- `features.parquet` 또는 `features.csv`
- `feature_order.txt`
- `parser_manifest.json`
- `row_validity_report.json`
- `external_merge_report.json`
- `sample_debug_rows.csv`

---

## 17. 버전 정책

다음 중 하나라도 바뀌면 parser spec 버전을 올린다.

- feature 공식 변경
- feature 추가/삭제
- output order 변경
- 외부 시리즈 merge 규칙 변경
- session 계산 기준 변경
- invalid-row 정책 변경

---

## 18. FPMarkets v2 change notes

- `VXN` 관련 3개 feature는 삭제되었다.
- risk proxy block은 `VIX`, `US10YR`, `USDX`의 broker-native series로 재정렬되었다.
- `AVGO`는 현재 FPMarkets MT5 환경 미확인으로 간주하고, mega8 constituent는 `AMD`로 교체되었다.
- `US10YR`와 `USDX`는 추상 alias(`TNX`, `DXY`)로 되돌리지 않는다. 이 버전의 공식 이름은 broker-native symbol명이다.

---

## 19. 최종 요약

이 문서의 핵심은 아래 한 줄이다.

> Python 파서는 “feature를 계산하는 코드”가 아니라, 학습과 실전이 동일 입력 의미를 공유하도록 만드는 **입력 제조 계약서**다.
