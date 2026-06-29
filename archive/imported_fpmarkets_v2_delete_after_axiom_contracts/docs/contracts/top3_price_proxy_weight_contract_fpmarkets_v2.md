# Top3 Price-Proxy Weight Contract FPMarkets v2

## 목적(Purpose, 목적)

이 계약(contract, 계약)은 Stage 04(4단계)의 58 feature(58개 피처) model input(모델 입력)에 쓸 monthly top3 weights(월별 top3 가중치)를 정의한다.

효과(effect, 효과)는 외부 구독 데이터(external subscription data, 외부 구독 데이터) 없이 로컬 MT5(`MetaTrader 5`, 메타트레이더5) closed bar(닫힌 봉)만으로 재현 가능한 proxy weights(대리 가중치)를 만드는 것이다.

## 경계(Boundary, 경계)

이 가중치는 `MT5 price-proxy weights(MT5 가격 대리 가중치)`다.

이 값은 다음을 뜻하지 않는다.

- NDX actual index weight(NDX 실제 지수 가중치)
- QQQ holdings weight(QQQ 보유비중)
- market cap weight(시가총액 가중치)
- float-adjusted weight(유동주식 조정 가중치)
- operating promotion(운영 승격)

## 대상 Basket(대상 바스켓)

고정 basket(바스켓)은 다음 세 symbol(심볼)이다.

- `MSFT`
- `NVDA`
- `AAPL`

## 계산 규칙(Calculation Rule, 계산 규칙)

각 월 `YYYY-MM`의 source row(원천 행)는 그 월 시작 전 마지막 공통 MT5 closed bar(닫힌 봉)다.

첫 월 `2022-08`에 prior bar(이전 봉)가 없으면 첫 공통 closed bar(닫힌 봉)를 bootstrap month(초기 월)로 쓴다.

공식(formula, 공식):

```text
symbol_weight = symbol_close / (msft_close + nvda_close + aapl_close)
```

세 weight(가중치)의 합은 `1.0`이어야 한다.

## CSV Schema(CSV 스키마)

산출물(output artifact, 출력 산출물)은 `foundation/config/top3_monthly_price_proxy_weights_fpmarkets_v2.csv`에 둔다.

필수 column(열):

- `month`
- `source_timestamp`
- `source_rule`
- `bootstrap_month`
- `weight_method`
- `msft_xnas_close`
- `msft_xnas_weight`
- `nvda_xnas_close`
- `nvda_xnas_weight`
- `aapl_xnas_close`
- `aapl_xnas_weight`
- `weight_sum`

## 사용 규칙(Use Rule, 사용 규칙)

이 산출물은 `top3_weighted_return_1`과 `us100_minus_top3_weighted_return_1`을 58 feature(58개 피처) 경로에 다시 포함하기 위한 proxy input(대리 입력)이다.

보고서(report, 보고서)와 registry(등록부)는 항상 `price-proxy(가격 대리)`라고 표시해야 한다.

