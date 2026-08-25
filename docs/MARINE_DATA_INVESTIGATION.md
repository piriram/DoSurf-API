# 해상정보 데이터 조사

> DoSurf-API 해상정보(파고·수온) 데이터가 어디서 오는지 정리하고, Open-Meteo 데이터의 신뢰성 문제를 계기로 조사한 대안 API와 서핑 앱들의 정확도 확보 방식을 기록한다.

- 작성일: 2026-08-25
- 참고 커밋: `845aa3c` (2026-05-15)

---

## 1. 현재 구조 — KMA + Open-Meteo 병합

두 개의 실시간 외부 API를 매 수집 주기마다 호출해 병합한 뒤 Firestore에 저장한다. 별도 스크래퍼는 없다.

```
기상청 단기예보 ─┐
                 ├─ 병합·오프셋 보정 ─ Firestore ─ iOS 앱(직접 읽기)
Open-Meteo Marine ┘
```

두 소스 모두 3시간 단위 발표시각(0·3·6·9·12·15·18·21시)에만 저장되며, iOS 앱은 이 API를 거치지 않고 Firestore를 직접 조회한다.

### 기상청(KMA) 단기예보 API
- **예보 모델.** 파고(WAV) 포함 육상·해상 단기예보. 위경도를 KMA 격자좌표로 변환해 조회, 실패 시 이전 발표시각으로 재시도
- Endpoint: `apihub.kma.go.kr/.../VilageFcstInfoService_2.0/getVilageFcst`
- 인증: `KMA_API_KEY` 환경변수 → `authKey` 파라미터
- 제공 항목: WAV(파고) · WSD/VEC(풍속·풍향) · TMP · POP · SKY · REH 등
- 파일: `scripts/forecast_api.py`

### Open-Meteo Marine API
- **예보 모델.** 전지구 해양 모델 기반(NOAA GFS Wave + DWD ICON Wave + ECMWF WAM 조합). API 키 없이 위경도만으로 조회
- Endpoint: `marine-api.open-meteo.com/v1/marine`
- 인증: 없음
- 제공 항목: `wave_height` · `wave_direction` · `sea_surface_temperature` (`om_` 접두사로 저장)
- 파일: `scripts/open_meteo.py`

### 병합·저장·트리거
- `app/services/collection.py`의 `run_collection()`이 해변별로 두 API를 순서대로 호출
- `scripts/storage.py`의 `save_forecasts_merged()`가 시간 기준으로 병합, Open-Meteo 파고에 **고정 오프셋 +0.5m**(`WAVE_HEIGHT_OFFSET`) 적용 후 저장
- 저장은 `POST /`(`app/api/routes.py`) 호출로 트리거 — 토큰 인증(`X-Job-Token`) 후 외부 스케줄러가 주기 호출하는 구조로 추정. 저장소 내 cron 설정은 없음
- 읽기 경로(`get_beach_forecast_by_id` 등)는 15분~1시간 캐시를 두고 Firestore에서 읽으며, 저장 직후 관련 캐시 키를 무효화

---

## 2. 문제 제기

Open-Meteo Marine은 전지구 모델 결과라 연안 지형이 복잡한 국내 해변에서는 오차가 클 수 있다는 우려. 현재 코드도 이를 의식한 듯 고정 오프셋(+0.5m)을 더하고 있지만, 지점별 특성을 반영하지 못하는 임시방편에 가깝다.

---

## 3. 대안 API 조사

| 소스 | 데이터 성격 | 주요 항목 | 인증·비용 | 비고 |
|---|---|---|---|---|
| 기상청 해양기상관측 (data.go.kr) | 실측 부이 | 유의·최대·평균파고, 파주기, 수온 + 품질값(MQC) | 무료 · 서비스키 (일 1만 건) | 미래 예보 아님 — 고정 부이 위치의 실측값. 예보 보정·검증용으로 적합 |
| KHOA 바다누리 (khoa.go.kr/oceandata) | 실측 | 조위, 수온, 해류 등 | 확인 필요 | 기존 API 2026-04-01 종료, 신규 포털 전환 중 — 접속 불가(503)로 스펙 미확인 |
| Stormglass.io | 모델 앙상블 | 파고, 파향, 스웰, 해류, 수온 등 시간별 7일 | 유료 (무료 티어 일 10건, 비상업만) | 여러 기상기관·AI 모델 통합 제공. 국내 특화는 아님 |

---

## 4. 참고 사례 — 서핑 앱들은 어떻게 정확도를 확보하나

| 앱 | 방식 | 확인 상태 |
|---|---|---|
| **Windy** | 자체 예보 모델 없이 ECMWF·GFS·ICON·Meteoblue를 "Compare Forecast"로 비교 노출. 자체 보정 모델 GFS+(GFS 원본을 격자 내 최댓값으로 보정)도 제공 | 확인됨 |
| **Windfinder** | 공식 도움말에 확인되는 건 관측소별 *과거 실측 통계*가 실측 기반이라는 것뿐. 예보값 자체에 지점별 통계보정(MOS)을 적용한다는 근거는 못 찾음 | 정정 — 이전엔 "예보 보정"이라고 과장했음 |
| **Surfline (LOLA → LOTUS)** | 2001년 LOLA부터 위성 파고 데이터 + 연안 부이 관측을 수심(bathymetry) 정보와 결합해 외해 스웰의 굴절·변형 계산. LOTUS는 여기에 머신러닝 추가 | 확인됨 (Surfline Labs 공식 자료) |
| **WSB FARM** | 웨더아이(WeatherEye)와 협업한 자체 파도예측 시스템, 파고·주기·풍향·수온 반영한 내러티브형 예보 제공. Surfline류 연안 변환 모델 사용 여부는 공개 자료로 미확인 | 확인됨, 단 Surfline과 같은 부류로 묶었던 건 근거 없는 추정이었음 |

**출처**
- [Windy Community — What source of weather data Windy use?](https://community.windy.com/topic/12/what-source-of-weather-data-windy-use)
- [Windy.app — 모델 비교(GFS+ 포함) 설명](https://windy.app/blog/what-is-icon-weather-model-forecast.html)
- [Windfinder — Help/FAQ: Weather statistics](https://www.windfinder.com/help/usage/weather-statistics.htm)
- [Surfline Labs — Surf Forecast Accuracy](https://medium.com/surfline-labs/surf-forecast-accuracy-b563605f104c)
- [Surfline — LOTUS swell model](https://www.surfline.com/lp/whatsnew/features/lotus-swell-model)
- [WSB FARM — 앱 서비스 공지](https://wsbfarm.com/board/NoticeView?boardIndex=58&pageNo=1&sessionToken=)

---

## 5. 무료·저가 대안 조사

> **먼저 확인할 것 — 라이선스 문제일 수 있다.** Open-Meteo의 무료 API는 *비상업적 용도 전용*이다. 앱에 광고나 유료 구독이 있다면 지금 무료 티어를 쓰는 것 자체가 약관 위반일 수 있고, 상업용은 월 $29부터 유료 전환이 필요하다. (→ DoSurf 앱은 완전 무료 앱으로 확인, 문제 없음)

| 소스 | 비용 | 형태 | 비고 |
|---|---|---|---|
| Open-Meteo Marine (현재 사용 중) | 비상업 무료 (일 1만 건) · 상업용 $29~/월 | REST, 키 불필요 | NOAA GFS Wave + DWD ICON Wave + ECMWF WAM을 이미 내부적으로 조합해 제공 |
| Copernicus Marine Service (CMEMS) | 완전 무료 (2028-06까지 보장, 상업용 포함) | NetCDF/GRIB 다운로드 + 파이썬 툴박스 | 전지구 해양파랑 1/12°(~9km) 해석·예보. REST 단건 조회 불가 — 자체 파이프라인 구축 필요 |
| ECMWF Open Data | 완전 무료 (2025-10부터 전면 개방) | GRIB2 원시 데이터 | 현재 25km, 2026년 중 9km까지 개방 예정. Open-Meteo가 이미 이 소스를 포함해서 제공 중이라 중복 가능성 |
| Stormglass.io | 무료 티어 일 10건(비상업)만 · 유료 €19~/월 | REST | 상업용으로 쓰기엔 무료 티어가 사실상 의미 없는 수준 |

### Copernicus Marine 상세 — 가격 · 정확도
- **가격**: 완전 무료, 상업적 이용 포함. 호출 한도 명시 없음(포털 가용성 SLA만 연 97%). 저작자 표시 + DOI 인용 의무. **2028-06-30까지만 무료 보장** — 이후 정책 미발표
- **해상도**: 전지구 파랑 제품(`GLOBAL_ANALYSISFORECAST_WAV_001_027`) 기준 0.083°(약 10km) · 3시간 간격 · 10일 예보 — Open-Meteo(0.25°, 약 25km)보다 촘촘함
- **검증치**: 전지구 제품 자체의 공식 RMSE는 문서에 미명시. 지중해 지역 구현체 기준 RMSE 0.21m · bias -0.03m(3.7%) — 한국 근해 검증치는 확인 안 됨
- **모델 특징**: Sentinel-1 SAR 위성 파랑 스펙트럼을 실시간 동화(assimilation)하는 세계 최초 운영 모델
- **접근 방식**: REST 단건 조회 불가. NetCDF-4 파일을 `copernicusmarine` 파이썬 툴박스로 내려받아 직접 파싱해야 함

**정리**
- 순수 비용만 보면 Copernicus Marine이 상업용까지 완전 무료라 가장 유리하지만, 데이터 파이프라인을 직접 구축해야 해서 지금 구조(Flask + 수집 스크립트)에 통합하는 작업량이 생긴다.
- 지금처럼 REST 호출 몇 줄로 붙이는 편의성을 유지하려면 Open-Meteo를 계속 쓰는 게 여전히 합리적이다.
- Stormglass는 이 프로젝트 규모에서 무료로 쓰기엔 호출 한도가 너무 낮아 실질적 대안이 아니다.

**출처**
- [Open-Meteo — Pricing](https://open-meteo.com/en/pricing)
- [Open-Meteo — Marine Weather API (소스 모델 구성)](https://open-meteo.com/en/docs/marine-weather-api)
- [Copernicus Marine — 무료 정책](https://help.marine.copernicus.eu/en/articles/4220312-i-just-opened-my-account-but-will-it-still-be-free-in-2-3-or-5-years)
- [Copernicus Marine — Service Commitments and Licence](https://marine.copernicus.eu/user-corner/service-commitments-and-licence)
- [Copernicus Marine — Global Ocean Waves Analysis and Forecast (제품 스펙)](https://data.marine.copernicus.eu/product/GLOBAL_ANALYSISFORECAST_WAV_001_027/description)
- [Copernicus Marine — SAR 위성 데이터 동화 발표](https://marine.copernicus.eu/news/world-premiere-operational-wave-forecasting-models)
- [ECMWF — Open Data 전환 발표](https://www.ecmwf.int/en/about/media-centre/news/2025/ecmwf-achieve-fully-open-data-status-2025)
- [Stormglass — Pricing](https://stormglass.io/pricing/)

---

## 6. 채택된 방향

**제약 조건**: 파이어베이스 비용은 현재 무료 등급 유지 · 연 지출 한도 10만원 · 앱은 광고·구독 없는 완전 무료 앱(Open-Meteo 무료 티어 라이선스 조건 충족)

| 결정 | 내용 |
|---|---|
| ✅ 채택 | KMA + Open-Meteo 유지 + 기상청 해양기상부이 실측 기반 해변별 보정계수 |
| ⏸ 보류 | Copernicus Marine (비용 $0이나 파이프라인 구축 필요) |
| ⏸ 보류 | KMA+Open-Meteo 가중 앙상블 (보정계수 적용 후 재검토) |
| ❌ 제외 | Stormglass (예산 초과) |

### 보정계수 산출 원리 (MOS)

Windfinder류가 쓰는 통계 보정을 가장 단순한 형태로 옮긴 것 — 모델이 이 지점에서 평소 얼마나 틀리는지를 실측으로 재서, 그 오차만큼 예보값을 밀어준다.

1. **예보값과 실측값을 같은 시각 기준으로 짝짓는다** — KMA/Open-Meteo가 저장한 예보 파고(predicted)와, 그 시각이 지난 뒤 가장 가까운 해양기상부이가 관측한 파고(observed)를 매칭
2. **오차를 계산한다** — `오차 = observed - predicted` (예: predicted 1.2m, observed 1.6m → 오차 +0.4m)
3. **최근 N일치 오차를 누적해 평균을 낸다** — 이 평균이 해당 해변의 고유 보정계수. 지금은 전국 공통 +0.5m 하나뿐인데, 해변마다 다른 값으로 대체
4. **다음 예보 저장 시 이 보정계수를 더한다** — `최종 파고 = predicted + 해당 해변의 보정계수`

편차가 무작위가 아니라 지형(수심·만/곶 형태)에 따라 일정한 방향으로 반복되기 때문에 통한다 — "이 해변은 모델이 항상 낮게 잡는다" 같은 패턴을 실측으로 계속 추적해 상쇄하는 방식이다.

### 구현 시 걸리는 부분
- 부이가 모든 해변 앞바다에 있는 게 아니라 해변마다 "가장 가까운 부이"를 지정해야 하고, 거리가 멀수록 보정 신뢰도가 떨어진다
- 데이터가 충분히 쌓이기 전(신규 해변, 초기 운영)엔 보정계수를 못 믿으니 기존 고정값(+0.5m)으로 폴백이 필요하다
- 계절별로 파도 패턴이 달라질 수 있어 전체 평균보다는 최근 N일 이동평균이 안전하다
- 파이어베이스 무료 등급을 유지하려면 부이 비교·보정 계산은 실시간이 아니라 기존 3시간 저장 주기에 맞춰 배치로 처리해, 현재의 쓰기 빈도·문서 수를 그대로 유지해야 한다
