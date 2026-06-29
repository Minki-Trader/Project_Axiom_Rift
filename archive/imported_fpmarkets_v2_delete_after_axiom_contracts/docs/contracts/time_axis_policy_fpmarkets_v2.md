# Time Axis Policy FPMarkets v2(시간축 정책)

## 결정(Decision, 결정)

FPMarkets v2 원천 `time_open_unix`와 `time_close_unix`는 지금 단계에서 직접 UTC(direct UTC, 직접 협정세계시)로 보지 않는다.

현재 정책(policy, 정책)은 이중 시간축(dual time axis, 이중 시간축)이다.

- `timestamp` 또는 `bar_close_key(봉 닫힘 키)`는 원천 브로커 시계 정렬 키(raw broker-clock alignment key, 원천 브로커 시계 정렬 키)다.
- `timestamp_event_utc(이벤트 UTC 타임스탬프)`는 세션 피처(session features, 세션 피처)를 계산하기 전에 별도로 만들어야 하는 실제 이벤트 시간(actual event time, 실제 이벤트 시간)이다.
- `timestamp_ny(뉴욕 타임스탬프)`는 `timestamp_event_utc`에서 `America/New_York(미국 뉴욕 시간대)`로 변환한 값이어야 한다.

## 물질화된 매퍼(Materialized Mapper, 물질화된 매퍼)

`foundation/features/session_calendar.py`가 현재 시간 매퍼(time mapper, 시간 매퍼)의 소유 모듈(owner module, 소유 모듈)이다.

- 브로커 시계 시간대(broker clock timezone, 브로커 시계 시간대): `Europe/Athens`
- 세션 시간대(session timezone, 세션 시간대): `America/New_York`
- 검토 실행(reviewed run, 검토된 실행): `20260424_broker_session_calendar_mapper`

## 이유(Why, 이유)

`20260424_time_semantics_probe` 실행(run, 실행)은 미국 주식 정규장(US cash session, 미국 현물 정규장) 기준으로 다음 결과를 냈다.

- 직접 UTC 일치율(direct UTC match ratio, 직접 UTC 일치율): `0.0`
- 브로커 시계 유사율(broker wall-clock-like ratio, 브로커 시계 유사율): `0.929082`

효과(effect, 효과): 원천 timestamp(타임스탬프)를 UTC(협정세계시)라고 가정하면 세션 피처(session features, 세션 피처)가 틀어질 수 있다.

## 정렬 규칙(Alignment Rule, 정렬 규칙)

외부 심볼(external symbols, 외부 심볼)과 `US100`의 정확한 정렬(exact alignment, 정확 정렬)은 원천 브로커 시계 정렬 키(raw broker-clock alignment key, 원천 브로커 시계 정렬 키)를 기준으로 한다.

효과(effect, 효과): 같은 FPMarkets 원천에서 나온 심볼끼리는 같은 닫힘 키(close key, 닫힘 키)로 비교할 수 있다.

## 세션 규칙(Session Rule, 세션 규칙)

미국 정규장 피처(US cash-session features, 미국 정규장 피처)는 원천 브로커 시계 키(raw broker-clock key, 원천 브로커 시계 키)에 `tz_convert("America/New_York")`를 바로 적용해서 계산하면 안 된다.

세션 피처(session features, 세션 피처)는 `foundation/features/session_calendar.py`의 매퍼(mapper, 매퍼)를 통해 계산한다.

부분 정규장(partial cash session, 부분 정규장)은 침묵 처리하지 않는다. 보고서(report, 보고서)와 row validity(행 유효성)는 부분 세션 경계를 보존해야 한다.

## 현재 경계(Current Boundary, 현재 경계)

현재 materializer(물질화 스크립트)는 브로커 시계에서 이벤트 UTC(event UTC, 이벤트 UTC)로 가는 세션 시간 매퍼(session time mapper, 세션 시간 매퍼)를 갖는다.

아직 다음은 주장하지 않는다.

- model readiness(모델 준비)
- runtime authority(런타임 권위)
- operating promotion(운영 승격)
