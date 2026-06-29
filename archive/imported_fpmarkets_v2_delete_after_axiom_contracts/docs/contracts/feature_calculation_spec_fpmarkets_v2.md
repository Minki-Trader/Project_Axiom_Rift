# Feature Calculation Specification FPMarkets v2

This document freezes the feature calculation contract for the current FPMarkets US100 / M5 research pipeline. It is intended to keep Python preprocessing, dataset export, ONNX training/inference, and MT5 EA runtime aligned.

## 1. Global conventions

- Main symbol: `US100` broker feed on `M5`.
- Broker context: `FPMarkets` MT5 environment.
- Broker-native external symbols for this version: `VIX`, `US10YR`, `USDX`.
- Timestamp basis: all features are computed on the **most recently closed bar** only. No partially formed bar values are allowed.
- Time-axis policy(시간축 정책): see `docs/contracts/time_axis_policy_fpmarkets_v2.md`. FPMarkets raw `time_open_unix` and `time_close_unix` are broker-clock alignment keys(브로커 시계 정렬 키) until a verified event-UTC conversion(이벤트 UTC 변환) or broker session calendar(브로커 세션 달력) is materialized.
- Storage timezone: stored timestamps may carry UTC-aware types for sorting, but session features must not treat raw broker-clock keys(원천 브로커 시계 키) as direct UTC(직접 협정세계시).
- Session timestamp: all session features must be derived from verified `timestamp_event_utc(이벤트 UTC 타임스탬프)` / `timestamp_ny(뉴욕 타임스탬프)` or an explicitly validated broker session calendar(브로커 세션 달력).
- Session definition: NY core cash session = 09:30 to 16:00 New York time. Daylight saving transitions must follow the IANA `America/New_York` calendar.
- Rolling windows are right-aligned and **include the current closed bar**.
- `min_periods = window`. Before warmup is complete, the feature value is `NaN`.
- Rolling standard deviation uses `ddof = 0`.
- If rolling standard deviation equals zero after warmup, z-score output is forced to `0.0`.
- `log` means the natural logarithm.
- Naming rule: features with `ratio` are raw ratios; features with `return`, `change`, or `percent` are centered return-like quantities.
- External series must be aligned by the same bar-close timestamp as the US100 series. No future fill. Forward-fill across exchange/session boundaries is forbidden.
- External-symbol features must be computed on each symbol's own raw `M5` series first, then merged onto the `US100` frame by exact bar-close timestamp.
- If an external source is missing for a required timestamp and no same-session resampling rule exists, the row is invalid for model input.
- ONNX input order is frozen to the feature order in Section 4. Changing order requires a new model artifact version.

## 2. Shared primitive definitions

- `ema(x, n)`: exponential moving average with span/period `n`.
- `sma(x, n)`: simple moving average with period `n`.
- `rsi(close, n)`: Wilder RSI on close prices.
- `atr(n)`: Wilder ATR on `(high, low, close)`.
- `bb_mid_20 = sma(close, 20)`.
- `bb_std_20 = rolling_std(close, 20, ddof=0)`.
- `bb_upper_20_2 = bb_mid_20 + 2 * bb_std_20`.
- `bb_lower_20_2 = bb_mid_20 - 2 * bb_std_20`.
- `kc_mid_20 = ema(close, 20)`.
- `kc_upper_20_1_5 = kc_mid_20 + 1.5 * atr(20)`.
- `kc_lower_20_1_5 = kc_mid_20 - 1.5 * atr(20)`.
- `zscore(x, w) = (x_t - mean(x_{t-w+1:t})) / std(x_{t-w+1:t})` with `ddof=0`.
- `simple_return_k = close_t / close_t-k - 1`.
- `log_return_k = ln(close_t / close_t-k)`.
- `bars_per_year_5m = 252 * 288` for annualized realized volatility in this FPMarkets v2 contract.

## 3. Special implementation rules

### 3.1 Session features

- `cash_open_today` is the **open price of the first M5 bar that starts at 09:30 NY time**.
- `cash_close_prev_session` is the **close price of the last M5 bar that ends at 16:00 NY time** of the prior valid NY trading session.
- `overnight_return` is calculated once per NY trading day and then forward-filled only within that same NY trading date.
- `minutes_from_cash_open` uses the **bar close timestamp**. Example: the bar closing at 09:35 NY time has value `5`.

### 3.2 Custom indicators not built into MT5

- `supertrend_10_3` is stored as **trend state** rather than raw line value: `+1` for uptrend, `-1` for downtrend.
- Supertrend baseline uses `hl2 = (high + low) / 2` and ATR(10) with multiplier `3`.
- Supertrend state is seeded from the current bar after the current `final_upper` / `final_lower` updates are applied. If the previous state is still undefined, evaluate the seed against the updated current `final_lower`; if that band is still unavailable, the seed resolves to the downtrend state `-1`.
- `vortex_indicator` is stored as a single spread value `VI+ - VI-` with lookback `14`.

### 3.3 Breadth basket conventions

- Frozen `mega8` basket for FPMarkets v2: `AAPL, AMZN, AMD, GOOGL, META, MSFT, NVDA, TSLA`.
- Frozen `top3` basket for FPMarkets v2: `MSFT, NVDA, AAPL`.
- `top3_weighted_return_1` requires a separate monthly-frozen weight table. Do not infer weights dynamically at runtime.
- Aggregate/breadth features use **simple returns**, not log returns, for interpretability and stable weighted averaging.
- This version does **not** contain `VXN`-dependent features. The prior `vxn_minus_vix` spread is removed rather than backfilled with a substitute.

## 4. Frozen feature definitions

| Feature | Class | Inputs | Formula | Notes |
|---|---|---|---|---|
| `log_return_1` | price_return | close | `ln(close_t / close_t-1)` | NaN on first bar. |
| `log_return_3` | price_return | close | `ln(close_t / close_t-3)` | NaN until 3 prior bars exist. |
| `hl_range` | price_range | high, low, close | `(high_t - low_t) / close_t` | Dimensionless intrabar range. |
| `close_open_ratio` | price_ratio | open, close | `close_t / open_t` | Raw ratio; not minus 1. |
| `gap_percent` | gap_return | open, close | `(open_t / close_t-1) - 1` | Simple percentage gap vs prior bar close. |
| `close_prev_close_ratio` | price_ratio | close | `close_t / close_t-1` | Raw ratio; not minus 1. |
| `return_zscore_20` | rolling_zscore | log_return_1 | `zscore(log_return_1, 20)` | Uses rolling mean/std, ddof=0. |
| `hl_zscore_50` | rolling_zscore | hl_range | `zscore(hl_range, 50)` | Uses rolling mean/std, ddof=0. |
| `overnight_return` | session_return | open, close, timestamp | `(cash_open_today / cash_close_prev_session) - 1` | Computed once per NY trading day and forward-filled within that trading day only. |
| `return_1_over_atr_14` | normalized_return | close, atr_14 | `((close_t / close_t-1) - 1) / (atr_14_t / close_t)` | Simple return normalized by ATR as fraction of price. |
| `close_ema20_ratio` | ma_ratio | close | `close_t / ema(close,20)_t` | Raw ratio. |
| `close_ema50_ratio` | ma_ratio | close | `close_t / ema(close,50)_t` | Raw ratio. |
| `ema9_ema20_diff` | ma_diff | close | `ema(close,9)_t - ema(close,20)_t` | Price-unit spread. |
| `ema20_ema50_diff` | ma_diff | close | `ema(close,20)_t - ema(close,50)_t` | Price-unit spread. |
| `ema50_ema200_diff` | ma_diff | close | `ema(close,50)_t - ema(close,200)_t` | Price-unit spread. |
| `ema20_ema50_spread_zscore_50` | rolling_zscore | ema20_ema50_diff | `zscore(ema20_ema50_diff, 50)` | Uses rolling mean/std, ddof=0. |
| `sma50_sma200_ratio` | ma_ratio | close | `sma(close,50)_t / sma(close,200)_t` | Raw ratio. |
| `rsi_14` | oscillator | close | `rsi(close,14)_t` | Wilder RSI on close. |
| `rsi_50` | oscillator | close | `rsi(close,50)_t` | Wilder RSI on close. |
| `rsi_14_slope_3` | oscillator_slope | rsi_14 | `(rsi_14_t - rsi_14_t-3) / 3` | Average per-bar slope over 3 bars. |
| `rsi_14_minus_50` | oscillator_centered | rsi_14 | `rsi_14_t - 50` | Centered RSI. |
| `stoch_kd_diff` | oscillator_spread | high, low, close | `%K(14,3,3)_t - %D(14,3,3)_t` | Default Stochastic parameters 14,3,3. |
| `stochrsi_kd_diff` | oscillator_spread | close | `stochrsi_%K(14,14,3,3)_t - stochrsi_%D(14,14,3,3)_t` | RSI length 14, stochastic length 14, K 3, D 3. |
| `ppo_hist_12_26_9` | oscillator_hist | close | `ppo(12,26)_t - signal_ema(ppo,9)_t` | PPO histogram. |
| `roc_12` | momentum | close | `(close_t / close_t-12) - 1` | Simple ROC over 12 bars. |
| `trix_15` | momentum | close | `(triple_ema(close,15)_t / triple_ema(close,15)_t-1) - 1` | 1-bar percent ROC of triple EMA(15). |
| `atr_14` | volatility | high, low, close | `atr(14)_t` | Wilder ATR. |
| `atr_50` | volatility | high, low, close | `atr(50)_t` | Wilder ATR. |
| `atr_14_over_atr_50` | volatility_ratio | atr_14, atr_50 | `atr_14_t / atr_50_t` | Raw ratio. |
| `bollinger_width_20` | bandwidth | close | `(bb_upper_20_2_t - bb_lower_20_2_t) / bb_mid_20_t` | BB uses SMA(20) and 2 std. |
| `bb_position_20` | band_position | close | `(close_t - bb_lower_20_2_t) / (bb_upper_20_2_t - bb_lower_20_2_t)` | Unclipped; may fall outside [0,1]. |
| `bb_squeeze` | squeeze_flag | close, high, low | `1 if BB(20,2) lies fully inside KC(20,1.5*ATR20), else 0` | Project convention for squeeze. |
| `historical_vol_20` | realized_vol | log_return_1 | `stdev(log_return_1,20) * sqrt(252*288)` | Annualized for 5-minute bars. |
| `historical_vol_5_over_20` | realized_vol_ratio | log_return_1 | `historical_vol_5_t / historical_vol_20_t` | Both HV series annualized identically. |
| `adx_14` | trend_strength | high, low, close | `adx(14)_t` | Standard ADX. |
| `di_spread_14` | trend_direction_spread | high, low, close | `plus_di(14)_t - minus_di(14)_t` | Directional spread. |
| `supertrend_10_3` | trend_state | high, low, close | `supertrend_state(atr_len=10, multiplier=3)_t` | Encoded as +1 uptrend, -1 downtrend. |
| `vortex_indicator` | trend_direction_spread | high, low, close | `vi_plus(14)_t - vi_minus(14)_t` | Recommended single-value encoding of the Vortex indicator. |
| `is_us_cash_open` | session_flag | timestamp | `1 if bar_close_time in NY core session (09:30,16:00], else 0` | Uses America/New_York calendar. |
| `minutes_from_cash_open` | session_clock | timestamp | `minutes(bar_close_time_ny - same_day_cash_open_ny)` | Signed minutes; 09:35 close => 5. |
| `is_first_30m_after_open` | session_flag | timestamp | `1 if 0 < minutes_from_cash_open <= 30, else 0` | Six M5 closes: 09:35..10:00. |
| `is_last_30m_before_cash_close` | session_flag | timestamp | `1 if 0 < minutes_to_cash_close <= 30, else 0` | Six M5 closes: 15:35..16:00. |
| `vix_change_1` | external_return | vix close | `(vix_t / vix_t-1) - 1` | Simple pct change of VIX level. |
| `vix_zscore_20` | external_zscore | vix close | `zscore(vix_level,20)` | Z-score of level, not return. |
| `us10yr_change_1` | external_return | us10yr close | `(us10yr_t / us10yr_t-1) - 1` | Simple pct change of broker-native `US10YR` level. |
| `us10yr_zscore_20` | external_zscore | us10yr close | `zscore(us10yr_level,20)` | Z-score of level, not return. |
| `usdx_change_1` | external_return | usdx close | `(usdx_t / usdx_t-1) - 1` | Simple pct change of broker-native `USDX` level. |
| `usdx_zscore_20` | external_zscore | usdx close | `zscore(usdx_level,20)` | Z-score of level, not return. |
| `nvda_xnas_log_return_1` | external_return | nvda close | `ln(nvda_close_t / nvda_close_t-1)` | Aligned to the same bar-close timestamp. |
| `aapl_xnas_log_return_1` | external_return | aapl close | `ln(aapl_close_t / aapl_close_t-1)` | Aligned to the same bar-close timestamp. |
| `msft_xnas_log_return_1` | external_return | msft close | `ln(msft_close_t / msft_close_t-1)` | Aligned to the same bar-close timestamp. |
| `amzn_xnas_log_return_1` | external_return | amzn close | `ln(amzn_close_t / amzn_close_t-1)` | Aligned to the same bar-close timestamp. |
| `mega8_equal_return_1` | breadth_aggregate | mega8 closes | `mean(simple_return_1_i for i in mega8)` | Frozen FPMarkets v2 mega8 basket = {AAPL, AMZN, AMD, GOOGL, META, MSFT, NVDA, TSLA}. |
| `top3_weighted_return_1` | breadth_aggregate | top3 closes, weight table | `sum(w_i * simple_return_1_i for i in top3)` | Recommended top3 = {MSFT, NVDA, AAPL}; weights supplied by separate monthly weight table. |
| `mega8_pos_breadth_1` | breadth_ratio | mega8 closes | `mean(1[simple_return_1_i > 0] for i in mega8)` | Range [0,1]. |
| `mega8_dispersion_5` | breadth_dispersion | mega8 closes | `stdev(simple_return_5_i across mega8, ddof=0)` | Cross-sectional dispersion. |
| `us100_minus_mega8_equal_return_1` | relative_strength | us100 close, mega8 closes | `us100_simple_return_1_t - mega8_equal_return_1_t` | Simple-return spread. |
| `us100_minus_top3_weighted_return_1` | relative_strength | us100 close, top3 closes | `us100_simple_return_1_t - top3_weighted_return_1_t` | Simple-return spread. |

## 5. MT5 / Python parity notes

- Prefer MT5 built-ins where they exist: MA, RSI, Stochastic, ATR, ADX, Bands.
- Read all indicator values from closed-bar buffers only. Runtime code should not use buffer index `0` until the bar is closed and the new-bar event is confirmed.
- For Python training data, use the same periods, smoothing conventions, and bar-close timing used by the EA.
- If a custom Python implementation is used for a built-in indicator, parity-test it against MT5 on a shared sample before dataset freeze.
- Export feature columns in the exact order listed in Section 4 and persist that order with the model metadata.

## 6. Recommended validation tests before first model training

1. Unit test each formula against a hand-checked mini sample.
2. Parity test Python vs MT5 on at least 500 consecutive bars for every built-in indicator-derived feature.
3. Verify all session flags across a daylight-saving transition week.
4. Verify that `overnight_return` changes only once per NY trading date.
5. Verify that external-symbol alignment never uses future timestamps and never forward-fills across session boundaries.
6. Freeze the feature order hash and store it with each ONNX artifact version.

## 7. Candidate rename notes for a future cleanup pass

- `supertrend_10_3` would be clearer as `supertrend_10_3_state`.
- `vortex_indicator` would be clearer as `vortex_spread_14`.
- `stoch_kd_diff` would be clearer as `stoch_k14_d3_diff` if multiple parameter sets are introduced later.
- `stochrsi_kd_diff` would be clearer as `stochrsi_14_14_k3_d3_diff` if multiple parameter sets are introduced later.

These are **not** required for FPMarkets v2, but they would reduce ambiguity if the feature catalog expands.
