# DoSurf-API

서핑 예보 앱 **두섭이**의 백엔드. 해변 32곳의 기상·해양 예보를 3시간마다 수집해
Firestore에 저장한다. iOS 앱([`piriram/DoSurf-iOS`](https://github.com/piriram/DoSurf-iOS))이
HTTP API가 아니라 **Firestore를 직접 읽는다.**

> **`piriram/do-surf-functions`는 이 저장소의 초기 사본이고 현행이 아니다.**
> Cloud Run **서비스 이름**이 `do-surf-functions`라서 헷갈리기 쉽다 —
> 그 서비스를 배포하는 소스는 이 저장소다. 저쪽에 코드를 고치면 반영되지 않는다.

---

## 지금 진행 중인 작업

해상 데이터 정확도 개선. **[`docs/marine-data-plan.md`](./docs/marine-data-plan.md)부터 읽을 것** —
현재 상태, 결정 사항, 바로 실행할 명령이 맨 위에 있다.

관련 문서:
- [`docs/marine-data-audit.md`](./docs/marine-data-audit.md) — 측정값과 근거
- [`docs/marine-data-audit.html`](./docs/marine-data-audit.html) — 같은 내용, 차트 포함
- [`docs/ios-migration.md`](./docs/ios-migration.md) — iOS에서 고칠 것

---

## 구조

```
server.py            ← HTTP 진입점 (Dockerfile → gunicorn server:app). 얇은 래퍼
main.py                 배치 진입점. 얇은 래퍼
app/
  api/routes.py         POST / (수집) · /monitoring-alert · /health
  services/collection.py  ← 수집 로직 본체
  clients/alerts.py     텔레그램 장애 알림
  config/settings.py    ISSUE_HOURS, FORECAST_DAYS 등 런타임 상수
jobs/                   api_functions.py, cleanup_old_forecasts.py
scripts/
  forecast_api.py       기상청 단기예보. 위경도 → 5km 격자(nx,ny) 변환
  open_meteo.py         Open-Meteo Marine. 지역별 모델 + 폴백 이중 호출
  storage.py            Firestore 병합 저장 + 조회 유틸
  config.py             config.json 접근자
  timeutil.py           naive KST 헬퍼
  beach_registry.py     해변 목록 메타데이터
  cache_utils.py        메모리 캐시
  firebase_utils.py     Firestore 클라이언트 (지연 초기화)
  locations.json        해변 32곳 정의
  windfinder.py         Windfinder 예보 페이지에서 파고·파주기 수집 (검증용)
  model_compare.py      파랑 모델을 Windfinder·Windy와 대조 — 편향/모양 분리
  compare_rollup.py     model_compare 누적분(jsonl)을 여러 날로 집계 — 결론은 여기서
  copernicus.py         Copernicus Marine(CMEMS) 파랑 예보 수집 (대안 후보 검증용)
  compare_period.py     iOS 파주기 추정식이 실제와 얼마나 다른지 측정
  grid_coverage.py      대조 지점의 결론을 어느 해변에 적용할 수 있는지 — 격자 일치 판정
config.json          ← 수집 주기·모델 선택 등 런타임 설정
```

Firestore 경로: `regions/{region}/{beach_id}/{YYYYMMDDHHMM}`
그 외 `_metadata`, `_region_metadata/beaches`, `_global_metadata/all_beaches`.

---

## 실행에 필요한 것

| 무엇 | 어디서 |
|---|---|
| `KMA_API_KEY` | 환경변수. `scripts/forecast_api.py`가 **import 시점에** 읽고 없으면 `ValueError` |
| Firebase 자격증명 | Cloud Run은 기본 인증. 로컬은 `private/keys/` 또는 `secrets/serviceAccountKey.json` |
| `COLLECT_JOB_TOKEN` | `POST /` 인증용 (`app/api/routes.py:26`). 없으면 비프로덕션에서만 통과 |
| `TELEGRAM_*` | 장애 알림용 (`app/clients/alerts.py`) |

`private/`와 `secrets/`는 `.gitignore` 대상이라 저장소에 없다.

### 로컬 준비 (한 번만)

**의존성은 `.venv`에 깐다.** 시스템 python으로는 `firebase_admin` import가 실패한다 —
"모듈이 없어서 Firestore를 못 쓴다"고 결론내기 전에 `.venv/bin/python3`로 실행했는지 볼 것.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

이후 모든 실행은 `.venv/bin/python3` 로 한다. `-m scripts.xxx` 형태를 쓰면
`scripts` 패키지 import가 맞는다.

**자격증명 두 개**는 iCloud 인계 폴더에 있다 (`~/Library/Mobile Documents/com~apple~CloudDocs/DoSurf-API 인계 자료/`).

```sh
# Firebase 서비스계정 키 — 이 경로에 두면 firebase_utils 가 자동으로 찾는다
mkdir -p private/keys
cp "<인계폴더>/serviceAccountKey.json" private/keys/serviceAccountKey.json
chmod 600 private/keys/serviceAccountKey.json

# 기상청 키 — 인계폴더 secrets.json 의 API_KEY
export KMA_API_KEY=$(python3 -c "import json;print(json.load(open('<인계폴더>/secrets.json'))['API_KEY'])")
```

### 확인된 사실 (2026-08-30 실측)

문서만 보고 추측하지 말라고 적어둔다. 아래는 실제로 돌려서 확인한 것이다.

- **기상청 단기예보에 수온(`TW`)이 없다.** 죽도 907건 응답의 카테고리는
  `PCP POP PTY REH SKY SNO TMN TMP TMX UUU VEC VVV WAV WSD` 14종뿐이다.
  수온은 Open-Meteo에서만 온다. 부이 관측(`kma_buoy.php`)은 별개 API이고
  `getWaveBuoyLstTbl`은 관측값이 아니라 **파고부이 지점 좌표 목록**이다.
- **기상청 파고(`WAV`)는 사실상 상수다.** 해변 32곳 전부 100% 채워지지만 값이
  지역별로 `0` 또는 `0.5`에 고정이다. 5km 육상 격자라 해양 파랑모델이 아니다.
  그래서 iOS는 파고를 Open-Meteo 우선으로 읽는다.
- **Open-Meteo 이중 호출이 실제로 동작한다.** 지역 모델로 파고를 받고,
  `models` 지정 시 빠지는 수온·조석을 폴백 모델로 한 번 더 채운다.
  결과에 `marine_source.fallback_fields: ['sea_surface_temperature', 'sea_level_height_msl']`
  가 남는다.
- **첨두주기는 `ecmwf_wam025`/`ecmwf_wam` 만 준다** (2026-08-30 실측, 2026-09-27 재확인).
  `best_match`·`ncep_gfswave025/016`·`gwam`·`meteofrance_wave` 는 `wave_peak_period`
  를 받아주기는 하되 값을 전부 `None` 으로 돌려준다. 폴백(`best_match`)으로도
  못 받으므로 **세 번째 호출**을 따로 한다.
  `wave_period` 는 평균주기 계열이라 서핑 앱이 쓰는 첨두주기보다 구조적으로 작다 —
  제주 대조에서 Windfinder 8.0초 대비 평균 MAE 2.6~3.1초, 첨두 1.08초였다.
  `wave.peak_period_s` 로 저장하고 출처는 `marine_source.peak_period_model` 에 남는다.
  **`period_s` 의 더 정확한 버전이 아니라 정의가 다른 별개 값이다.**
- **과거를 소급 복원할 수 없다** (2026-09-27 실측). Open-Meteo marine 은 과거
  날짜에 `wave_peak_period` 를 정상적으로 돌려주지만, **그날 발표된 예보가 아니라
  최신 런의 값**이다. 저장된 옛 기록과 같은 날짜·같은 모델의 평균주기를 다시 받아
  비교하면 00시만 일치하고 뒤로 갈수록 벌어진다(속초 9/2: 당시 6.95 → 지금 7.70).
  그래서 파주기 축을 소급해 채우면 "지금의 재분석 vs 당시 Windfinder 예보"가 되어
  **예보시점 축이 새로 어긋난다.** 표본은 앞으로 쌓는 것만 쓴다.
- **호출 수**: 해변 32곳 × 1회 수집 85콜 × 하루 8회 = **680콜/일** (무료 한도 10,000).
  지역 모델이 폴백/첨두 모델과 같으면 그만큼 줄어든다.
- **Firestore 쓰기까지 검증됐다.** `wave.period_s`, `tide`, `marine_source`가
  실제 문서에 기록되는 것을 확인했다.

### 수집을 지금 한 번 돌리려면

스케줄러(정시+15분, 3시간 간격)를 기다릴 필요 없다. 배포된 서비스에 직접 친다.
**배포된 리비전으로 도는 것**이라 배포 검증도 겸한다.

```sh
TOKEN=$(gcloud secrets versions access latest --secret=dosurf-collect-job-token)
curl -sS -X POST https://do-surf-functions-900402500777.asia-northeast3.run.app/ \
  -H "X-Job-Token: $TOKEN"
```

응답의 `partial: 32 / success: 0`은 **정상이다.** 기상청은 3일치만 주는데
Open-Meteo는 더 멀리까지 줘서 항상 90% 조건(`collection.py:156`)에 걸린다.
실패는 `failed` 값으로 판단할 것.

### 자격증명 없이 되는 것

`scripts/open_meteo.py`는 인증이 필요 없다. Windfinder 대조 도구
(`scripts/model_compare.py`, `scripts/windfinder.py`)도 Firestore를 쓰지 않는
경로가 있다. Firestore 조회가 필요한 `scripts/compare_period.py`만 키가 필요하다.

---

## 검증 도구 사용법

### 모델이 Windfinder와 얼마나 맞는지

```sh
.venv/bin/python3 -m scripts.model_compare --spot sokcho --from-windfinder \
  --out data/model_compare.jsonl
```

`--from-windfinder` 가 예보 페이지에서 파고·파주기를 직접 읽어 넣는다.
지점은 열두 곳이 정의돼 있다(`REFERENCE_SPOTS`) — `sokcho`, `jeju`, `wolpo`,
`mallipo`, `seogwipo`, `jungmun`, `mosulpo`, `hamdok`, `yeosu`, `gisamun`,
`donghae`, `ulsan`. 그중 `seogwipo` 는 자동 수집에서 빠져 있다(아래 참조).

### ⚠️ 대조 지점 좌표는 해변 좌표가 아니다

대조는 Windfinder 지점 좌표로 하고, 실제 수집은 `locations.json` 의 해변 좌표를
`latlon_to_xy()`(기상청 격자)와 `fetch_marine()`(Open-Meteo)에 그대로 넘긴다
(`app/services/collection.py:75` · `:131`). **둘이 다르고, 대부분 Open-Meteo
격자도 다르다.**

아래는 2026-09-27에 **운영 Firestore 의 `marine_source.grid_lat/grid_lon` 를
읽어** 대조 지점의 격자와 맞대본 것이다. 문서 추측이 아니라 실제 수집값이다.

| 지역 | 수집 모델 | 해변 | 담당 대조지점 | 격자일치 | 수집스냅 중앙 | 지점거리 최대 |
|---|---|---|---|---|---|---|
| busan | best_match | 3 | — 없음 — | 0/3 | 3.2km | — |
| gangneung | ncep_gfswave016 | 7 | donghae · sokcho | 1/7 | 9.1km | 43.8km |
| jeju | best_match | 6 | hamdok · jeju · seogwipo | 2/6 | 16.9km | 23.8km |
| pohang | ncep_gfswave016 | 5 | ulsan · wolpo | 3/5 | 14.8km | 23.8km |
| sokcho | ncep_gfswave016 | 3 | sokcho | 1/3 | 12.2km | 16.1km |
| west_south | best_match | 2 | mallipo · yeosu | 1/2 | 4.3km | 32.2km |
| yangyang | ncep_gfswave016 | 6 | gisamun | **6/6** | 7.7km | 4.5km |

이 표는 `jungmun`·`mosulpo` 추가 전 값이다. 현재 수치는 `grid_coverage.py` 로 본다.

합계 14/32곳만 같은 격자다. 지점 추가 전에는 sokcho 가 동해안 16곳을 대표하며
그중 15곳이 격자가 달랐다.

**격자 비교는 그 지역이 실제 쓰는 모델로 해야 한다.** 모델마다 격자 해상도가
다르다 — `best_match` 는 `(33.208336, 126.29167)` 처럼 촘촘하고(수집 스냅
0.62~8.7km), `ncep_gfswave016` 은 `(38.0, 128.83334)` 처럼 1/6도 간격이다
(스냅 3.45~18.6km). 한 모델로 전 지역을 계산하면 jeju·west_south·busan 이
틀리게 나온다.

**수집 자체는 해변에서 가깝다** — 스냅거리 중앙값 8.7km · 최대 18.6km(함덕).
문제는 수집이 먼 격자를 쓰는 게 아니라 **대조 지점과 다른 격자를 쓰는 것**이다.

**격자가 다르면 순위도 편향도 전이되지 않는다.** 2026-09-27 실측이다.

| | 값 |
|---|---|
| 격자가 다른 15곳의 파고차 | 중앙값 **0.020m** · 최대 0.083m |
| 격자가 같은 14곳의 파고차 | **0.000m** (같은 칸이니 당연하다) |
| 모델 1·2위 편향제거 MAE 차 | **0.001m** (4주 집계) |

**공간 차이가 모델 차이를 20~80배 압도한다.** 그래서 대조에서 "이 모델이 1위"라고
나와도 격자가 다른 해변에서는 그 순위가 유지된다는 보장이 없다. 「보정계수를
넣을 때」의 금지 규칙이 통계적 이유(σ) 말고도 이 구조적 이유를 함께 갖고 있다.

**모델 호출 좌표를 해변 좌표로 옮기는 것은 해법이 아니다.** 기준값(Windfinder
파고·파주기)은 그 지점 좌표에 대한 예보다. 모델만 해변으로 옮기면 같은 크기의
공간 오차가 기준값 비교에 들어와, 위치 차이와 모델 오차를 구분할 수 없게 된다.

### 결론을 어느 해변에 적용할 수 있나 — `scripts/grid_coverage.py`

```sh
.venv/bin/python3 -m scripts.grid_coverage          # 표로 확인
.venv/bin/python3 -m scripts.grid_coverage --save   # data/grid_coverage.json 갱신
```

지점별로 **격자가 같은 해변**(결론 적용 가능)과 **다른 해변**(적용 불가)을 가른다.
`--save` 로 만든 파일을 `model_compare.py` 가 읽어 출력에 찍는다 — 파일이 없으면
"격자 커버리지를 모른다"고 경고한다. **`config.json` 의 `region_models` 를 바꾸면
다시 돌릴 것.** 격자는 모델마다 다르다.

현재 **16/29곳**에 적용할 수 있다. `gisamun` 이 yangyang 6곳 전부를,
`jungmun`·`mosulpo` 가 중문·사계를 정확히 덮는다.

**적용 불가로 남은 것:** 강릉 4곳(경포·사천·사천진·금진)과 삼척 용화는 그 격자에
떨어지는 Windfinder 지점을 못 찾았다 — `mukho`·`santyoku`·`tonghae` 는 전부
`donghae` 와 같은 칸이고, 강릉 본체 페이지들은 파도 데이터가 없다. 고성 2곳,
영덕 부흥, 울산 진하, 고흥 남열, busan 3곳도 공백이다.

**적용 가능 해변이 0곳인 지점은 자동 수집에서 뺀다.** `seogwipo` 가 그래서
빠졌다 — 격자가 `(33.21, 126.54)` 로 어느 해변과도 맞지 않는다. 정의는 남겨
뒀으니 필요하면 `--spot seogwipo` 로 손으로 돌린다. `ulsan`·`yeosu` 는 0곳이지만
그 지역의 유일한 지점이라 근사 참고용으로 남겨 뒀다.

`--spot` 이름과 Windfinder slug 는 다를 수 있다(`seogwipo` 의 페이지는
`seogwipo_jeju-do_south_korea`). 매핑은 `REFERENCE_SPOTS` 의 `windfinder` 필드다.
**2026-09-27 까지 이 필드가 쓰이지 않아** `--spot` 이름을 그대로 slug 로 던지고
있었다 — 짧은 이름만 우연히 동작하던 상태였고 고쳤다.

**동해안은 `sokcho` 하나로 대표할 수 없었다.** 2026-09-27 전까지 `sokcho` 가
sokcho+yangyang+gangneung 16곳을 대표했는데 그중 15곳이 다른 격자였다.
`gisamun`(기사문해변 자체)을 넣어 yangyang 을 6/6 로 맞추고, `donghae` 로
강릉 남부를 받게 했다.

**제주는 한 지점으로 대표할 수 없다.** locations.json 의 제주 6곳이 남(33.22)부터
북동(33.56)까지 흩어져 있고 받는 스웰이 다르다. 2026-09-27 같은 날 Windfinder
파주기가 `seogwipo` 6→9초, `jeju`(북서) 5→7초였다. 그래서 남부(`seogwipo`)와
북동(`hamdok`, 함덕해변과 0.2km)을 따로 잰다.

**판별력은 지점마다 다르다.** 기준값이 하루 종일 평탄한 날은 모델을 구분할 수
없다 — 2026-09-27 `sokcho` 파주기는 8시각 전부 5.0초였고, 같은 날 `yeosu` 는
5→10초로 움직였다. 표본 수(`n`)만 보지 말고 그 날 기준값이 변했는지도 볼 것.
`--out` 으로 누적해야 여러 날 비교가 쌓인다.

**원시값은 순위와 별도로 저장된다.** 대조 순위는 기준값이 있는 파고·파주기로만
낼 수 있다 — Windfinder 페이지에 있는 것은 파고·파주기·풍속·풍향·기온·기압뿐이고
**스웰/풍파 분리가 없다**(2026-09-27 셀 목록 확인). 그래도 스웰·풍파·수온·해류를
`EXTRA_VARIABLES` 로 함께 받아 `results[].extra` 에 남긴다. **변수를 늘려도 API
콜 수는 그대로**(한 요청에 함께 온다)이고, 과거는 소급해서 받을 수 없으니 지금
안 받으면 그 날짜만큼 영구 손실이다. 기록 크기는 건당 3.0KB → 6.7KB 로 늘었다
(하루 4건 = 27KB/일). 순위·판정 로직은 `extra` 를 쓰지 않으므로 변수를 더 넣어도
결론이 바뀌지 않는다.

> ⚠️ **ecmwf 계열은 스웰·풍파를 아예 주지 않는다** (2026-09-27 실측).
> `ecmwf_wam025`·`ecmwf_wam` 은 파고 총합과 첨두주기만 주고 스웰·풍파·수온·해류가
> 전부 `None` 이다. 그래서 `config.json` 의 `region_models` 를 ecmwf 로 바꾸면
> 스웰·풍파 필드가 전부 빈다 — 지금 구조(파고는 지역 모델, 첨두주기만 ecmwf에서
> 별도 호출)를 유지해야 하는 이유 하나가 이것이다.
> 출력의 `[원시값 · 순위와 무관]` 줄이 모델별로 몇 개를 받았는지 보여준다.

**표본을 늘리는 방법은 지점 추가뿐이다.** 같은 날 여러 번 돌려도 롤업이
`(지점, 날짜)` 로 중복을 제거해 최신 것만 남기므로 표본은 하루 1개다.
과거 날짜로 다시 받는 것도 안 된다 — 아래 「과거를 소급 복원할 수 없다」 참조.

지점 좌표는 **Windfinder 예보 페이지 HTML 의 `"lat"`/`"lon"` 값**을 쓴다.
`locations.json` 의 해변 좌표가 아니다(1km 남짓 차이 난다). 기준값을 만든 쪽의
좌표로 재야 격자 스냅이 같은 조건이 된다. `sokcho`·`jeju` 는 2026-09-27에
페이지 값과 0.00km 일치를 확인했다.

**`busan`(송정·다대포·광안리 3곳)은 아직 대조 지점이 없다.** Windfinder 에
`songjeong`·`dadaepo`·`gwangalli`·`haeundae`·`gijang`·`ilgwang`·`busan` 이
전부 404다(2026-09-27 확인). 이름이 다른 페이지를 찾으면 `REFERENCE_SPOTS` 에
추가할 것.

**지점 후보를 찾는 방법.** Windfinder 검색 페이지는 SPA 라 HTML 에 결과가 없고
`/region/`·`/country/` 경로도 404다. 대신 **기존 지점 페이지에 인접 지점 링크가
10개씩 박혀 있다** — `/forecast/<slug>` 를 긁으면 후보가 나온다. 거기서 얻은
`seogwipo`·`hamdok`·`yeosu` 가 실제로 파고·파주기 8/8 로 파싱됐다.
`*_airport`·`*-air-base` 처럼 공항·관측소 지점은 파도 데이터가 없어
`reference_series` 가 파싱 실패로 떨어진다(`gangneung` 이 그 경우다).
좌표는 페이지 HTML 의 `"lat"`/`"lon"` 값을 쓴다.

**파주기는 첨두(peak)끼리만 비교한다.** 기준값인 Windfinder가 화면에 쓰는 값이
첨두주기라서다. 이 스크립트는 `wave_peak_period` 를 함께 요청하고, 값이 오는
모델은 첨두로 재고 안 오는 모델은 평균주기로 폴백한다. 어느 쪽을 썼는지는
기록의 `period_kind`(`"peak"`/`"mean"`)와 출력의 `주기축` 열에 남는다.
**평균주기 모델은 파주기 순위에서 뺀다** — 정의가 다른 값이라 구조적으로
작게 나오고, 섞으면 "평균주기 모델이 이겼다"는 가짜 결론이 된다.

**첨두주기를 주는 모델은 `ecmwf_wam025` · `ecmwf_wam` · `cmems_peak` 뿐이다**
(2026-09-27 6모델 실측). 나머지는 변수를 거부하지 않고 24개 전부 `None` 으로
돌려준다. 그래서 파주기 후보 수가 파고보다 적고, **파고 1위와 갈리는 게 정상이다** —
수집 경로도 파주기만 별도 모델에서 받는다(`config.json` 의 `peak_period_model`).

> ⚠️ **2026-09-27 이전 기록 54건은 파주기가 평균주기 축이다.**
> 그때는 이 스크립트가 `wave_peak_period` 를 요청하지 않았다. 롤업이
> `period_kind` 유무로 그 날들을 파주기 집계에서 분리하고 몇 날인지 알려준다.
> **그 날들의 파주기 순위는 근거로 쓸 수 없다.** 파고 결과는 영향 없다.

### Windy까지 3자 대조

```sh
.venv/bin/python3 -m scripts.model_compare --spot sokcho --from-windfinder \
  --reference-windy 1.3,1.2,1.1,1.0,1.0,0.9,0.8,0.7 \
  --out data/model_compare.jsonl
```

Windy 값은 **사람이 windy.com에서 읽어 넣는다.** 자동화 경로가 없다:

- Windy Point Forecast API **무료 Trial은 난수를 돌려준다** — 공식 문구가
  "randomly shuffled and slightly modified data"다. 검증에 쓰면 안 된다.
- 실데이터는 Professional **€990/년**뿐이다.
- 스크래핑은 하지 말 것. windy.com은 WebGL SPA라 HTML 파싱이 불가능하고
  ToS에도 걸린다.

**Windy의 파랑 모델은 전부 우리가 이미 쓰는 모델이다.** 표에서 `*` 가 그 표시다.

| Windy 모델명 | 실제 기관/모델 | Open-Meteo 이름 |
|---|---|---|
| `gfsWave` | NOAA/NCEP GFS-Wave (WW3) | `ncep_gfswave025` · `ncep_gfswave016` |
| `iconWave` | DWD GWAM | `gwam` |
| `iconEuWave` | DWD EWAM | `ewam` — **한국은 커버리지 밖**(2026-08-30 확인, "No data is available for this location") |

그러므로 한국에서 Windy가 보여주는 파랑 모델은 `gfsWave`·`iconWave` 둘뿐이고,
이 대조가 재는 것은 "Windy 예보가 더 맞나"가 아니라
**"같은 모델을 Windy가 어떻게 격자 스냅·보간했나"** 다.

출력의 `[기준끼리]` 줄이 Windy와 Windfinder가 서로 얼마나 다른지를 먼저 보여준다.
모델 1·2위 차이가 이 값보다 작으면 순위가 기준 선택에 좌우된다는 뜻이라
스크립트가 경고한다. 그 경고가 뜨면 순위를 근거로 쓰지 말 것.

**출력 읽는 법 — MAE만 보면 안 된다.** MAE는 성격이 다른 둘을 한 숫자에 섞는다.

| 열 | 뜻 | 고치는 방법 |
|---|---|---|
| 편향 | 이 지점에서 늘 얼마나 높게/낮게 나오는가 | 상수를 더한다 (보정계수) |
| 편향제거 MAE | 편향을 뺀 뒤 남는 오차 = 진짜 모양 오차 | 모델을 바꾼다 |
| 상관계수 | 오르내리는 흐름이 같은가 | 1에 가까우면 경향성 일치 |

모델은 **편향제거 MAE와 상관계수로 고르고**, 남은 편향은 보정계수로 처리한다.
2026-08-30 속초에서 전 모델 상관이 0.98을 넘었다 — 흐름은 이미 맞고 차이는
대부분 편향이었다.

기준값이 하루 종일 같으면(제주에서 실제로 있었다) 상관계수가 정의되지 않아
`-` 로 나온다. 그런 날은 경향성 판단이 불가능하니 다시 재야 한다.

> ⚠️ **이 대조는 독립 검증이 아니다.** Windfinder는 WW3(NOAA)를 쓰고
> Open-Meteo의 `ncep_gfswave*` 도 같은 소스다. 높은 일치도가 곧 정확도는 아니다.
> 자세한 건 `docs/marine-data-audit.md` 「기준을 Windfinder로」.

### iOS 파주기 추정식이 얼마나 틀리는지

```sh
.venv/bin/python3 -m scripts.compare_period          # 기본 5개 지역
.venv/bin/python3 -m scripts.compare_period 1001 3001 # beach_id 지정
```

Firestore의 기상청 풍속(iOS가 실제로 쓰는 값)으로 추정식을 재현해 Open-Meteo
실제 파주기와 맞대본다. Firestore 조회가 필요하므로 서비스계정 키가 있어야 한다.

### 보정계수를 넣을 때

**하루치로 상수를 박지 말 것.** 예전에 제거한 `+0.5` 보정이 그렇게 들어왔다.
여러 날 `data/model_compare.jsonl` 을 쌓아 편향 평균을 구한 뒤에 넣는다.

### Copernicus Marine(CMEMS) 대안 후보 재기

```sh
.venv/bin/pip install -r requirements-dev.txt      # 배포엔 안 들어간다
.venv/bin/copernicusmarine login                   # 무료 계정 필요, 한 번만
.venv/bin/python3 -m scripts.copernicus            # 단독 확인 (속초)

.venv/bin/python3 -m scripts.model_compare --spot sokcho --from-windfinder \
  --models best_match,ncep_gfswave016,ecmwf_wam025,cmems,cmems_peak \
  --out data/model_compare.jsonl
```

`cmems` / `cmems_peak` 는 Open-Meteo 모델이 아니라 CMEMS를 가리키는 가짜
모델명이다. 같은 자료를 파주기만 다르게 읽는다:

| 이름 | CMEMS 변수 | 뜻 |
|---|---|---|
| `cmems` | `VTM10` | 평균주기 — Open-Meteo `wave_period` 와 같은 계열 |
| `cmems_peak` | `VTPK` | 첨두주기 — Windfinder·서핑 앱이 화면에 쓰는 값 |

**파주기 순위에서 이 둘이 갈리면 결론이 바뀐다.** 지금까지 "파주기가 안 맞는다"고
본 것(제주 8/28 Windfinder 10~11초 vs 우리 5.4~7.3초, docs/ios-migration.md)이
모델 문제가 아니라 **정의가 다른 값을 비교하고 있었던 것**일 수 있다.

제품: `cmems_mod_glo_wav_anfc_0.083deg_PT3H-i` — 0.083°(~9km) · 3시간 간격 ·
10일 예보. **UTC 3시간 격자가 KST로 옮겨도 0,3,...,21시에 그대로 떨어진다**
(+9h 가 3의 배수라서). `ALLOWED_HOURS` 와 보간 없이 맞는다.

주의할 점:

- **수온·조석이 이 제품에 없다.** 파랑 전용이다. CMEMS로 갈아타도 수온은
  Open-Meteo에 계속 의존해야 한다.
- **`cell_selection=sea` 같은 옵션이 없다.** 가장 가까운 격자가 육지면 NaN이
  온다. `copernicus.py` 의 `_pick_sea_cell()` 이 ±0.5° 상자에서 유효한 칸 중
  제일 가까운 것을 직접 고른다.
- 자격증명이 없으면 툴박스가 **대화형으로 아이디를 묻고**, 배치에서는 EOF로
  끊겨 `None` 이 돌아온다. `has_credentials()` 가 먼저 걸러낸다.
- 무료지만 **2028-06-30까지만 보장**이다 (docs/MARINE_DATA_INVESTIGATION.md).

### 매일 자동으로 표본 쌓기

모델 궁합은 하루치로 못 정한다 — 1·2위 차이가 측정 노이즈보다 작다.
표본이 자동으로 모이도록 launchd 에이전트를 걸어뒀다.

```sh
bash scripts/daily_compare.sh            # 손으로 한 번
launchctl start com.dosurf.compare       # 에이전트를 즉시 한 번
launchctl list | grep dosurf             # 등록 확인
tail -30 data/compare_log/$(date +%F).log
```

- 매일 **09:30 KST**. Windfinder가 지나간 시각도 페이지에 유지하므로 새벽일
  필요가 없고, 맥이 켜져 있을 시간을 고른 것이다. 꺼져 있으면 launchd가 다음
  기상 때 한 번 밀어서 실행한다
- 대상은 `sokcho`, `jeju`. 결과는 `data/model_compare.jsonl` 에 append
- 모델 목록에 **`ecmwf_wam025` 와 `ecmwf_wam` 둘 다** 들어 있다. 첨두주기를 주는
  모델이 이 둘뿐이라, 하나만 넣으면 파주기에 비교 대상이 없어 순위가 성립하지 않는다
- **종료코드만 믿지 않는다.** Windfinder 파싱이 깨지면 기준값이 비어도 스크립트는
  정상 종료한다. 그래서 "기록 추가" 문구가 실제로 찍혔는지 확인한 뒤 실패로 센다
- `cmems` 는 뺐다 — 자격증명이 만료되면 조용히 실패하고 파고에서 이기지도 않았다.
  필요하면 손으로 `--models` 에 `cmems,cmems_peak` 를 붙인다
- Windy 값은 자동으로 못 받는다. 나중에 `--reference-windy` 로 같은 날짜를 다시
  돌리면 롤업이 최신 기록만 쓴다
- 로그는 `data/compare_log/` 에 30일치. gitignore 대상

**끄려면:**

```sh
launchctl unload ~/Library/LaunchAgents/com.dosurf.compare.plist
rm ~/Library/LaunchAgents/com.dosurf.compare.plist
```

### 누적분으로 결론 내기

```sh
.venv/bin/python3 -m scripts.compare_rollup
.venv/bin/python3 -m scripts.compare_rollup --spot sokcho --reference windy
```

지점별로 날짜를 모아 편향제거 MAE 평균·편향 평균·**편향 표준편차**·1위 획득
횟수를 낸다. 판정 규칙:

- 표본 5일 미만 → 결론 보류
- 1위가 날마다 바뀌고 최다 득표가 60% 미만 → 아직 노이즈. 더 쌓을 것
- 편향 표준편차가 편향 절댓값의 절반 미만 → 상수 보정계수 후보. 아니면 상수화 금지
- **파주기는 첨두주기(`period_kind: "peak"`)로 잰 날만 집계한다.** 평균주기로
  기록된 날은 축이 달라 따로 세고 순위에서 뺀다. 2026-09-27 이전 54건이 전부
  그쪽이라 파주기 표본은 실질적으로 그날부터 다시 시작이다

`data/model_compare.jsonl` 초기 2건(2026-08-30)은 편향·상관 분리 이전 스키마라
MAE만 있다. 롤업이 그 날짜 수를 따로 알려주고 편향제거 평균에서 제외한다.

**2026-09-27 집계 결과 — 파고는 결론이 났다. 다시 재지 말 것.**

sokcho 24일·jeju 22일을 쌓아도 1위가 안 굳는다(득표 48%·45%). 1·2위 편향제거
MAE 차이가 측정 노이즈보다 작다(sokcho 0.039 vs 0.040). 더 쌓아서 바뀔 성질이
아니라 **후보 모델들이 실질적으로 같은 정확도**라는 뜻이다. `config.json` 의
현재 선택을 유지한다.

보정계수도 못 넣는다 — sokcho는 편향이 -0.009로 애초에 없고, jeju는 편향 -0.201에
편향σ 0.172로 「σ < |편향|/2」 규칙에 걸린다. 수치 전체는
[`개발로그/2026-09-27.md`](./개발로그/2026-09-27.md).

`--reference windy` 는 **집계할 값이 없다.** 54건 전부 `reference_windy: null`
이다 — 아래 「매일 자동으로 표본 쌓기」대로 자동 수집이 Windy를 안 받기 때문이고
설계대로다. 쓰려면 사람이 `--reference-windy` 로 며칠치를 채워야 한다.

### ⚠️ 수집을 돌리면 데이터가 지워진다

`run_collection()`은 수집 후 **7일 지난 예보 문서를 삭제한다**
(`app/services/collection.py:203`). 운영 Firestore에 붙은 채로 `python3 main.py`를
돌리면 실제 삭제가 일어난다. 조회만 하려면 수집 함수를 부르지 말 것.

### 자격증명 없이 로직만 돌려보기

`scripts/open_meteo.py`는 **인증이 필요 없어 그대로 돌아간다.**

```sh
python3 -c "
from scripts.open_meteo import fetch_marine
h, m = fetch_marine(37.9723, 128.7595, forecast_days=2, region='yangyang')
print(m); print(h[12])"
```

저장 로직까지 보려면 Firebase를 스텁으로 갈아끼운다.

```python
import sys, types
fake = types.ModuleType("scripts.firebase_utils")
class FakeBatch:
    def set(s, ref, data, merge=False): print(getattr(ref, "_id", "?"), data)
    def commit(s): pass
class FakeRef:
    def __init__(s, i="?"): s._id = i
    def document(s, i): return FakeRef(i)
    def collection(s, i): return FakeRef(i)
class FakeDB:
    def batch(s): return FakeBatch()
    def collection(s, n): return FakeRef(n)
fake.db = FakeDB()
sys.modules["scripts.firebase_utils"] = fake
cache = types.ModuleType("scripts.cache_utils")
cache.invalidate_pattern = cache.get = cache.set = lambda *a, **k: None
sys.modules["scripts.cache_utils"] = cache

from scripts.storage import save_forecasts_merged
```

기상청 경로까지 밟으려면 `KMA_API_KEY=dummy`를 주면 된다 —
import는 통과하고 API 호출만 실패해 `has_kma=False` 경로로 빠진다.

---

## 알아둘 것

**시간대.** Cloud Run은 UTC인데 기상청 `fcstDate/Time`과 Open-Meteo(`timezone=Asia/Seoul`)는
둘 다 naive KST다. `datetime.now()`를 쓰면 9시간 어긋난다.
`scripts/timeutil.kst_naive_now()`를 쓸 것. **이 버그가 두 군데 있었다** —
예보 범위 계산과 기상청 발표시각 선택.

**파랑 모델은 지역마다 다르다.** `config.json`의 `marine.region_models`.
**코드에 박지 말 것** — 근거가 며칠치 표본이라 바뀔 가능성이 높다.
근거는 `docs/marine-data-audit.md`.

**파고에 `+0.5`를 더하지 말 것.** 예전에 있던 보정이고 제거했다.
유료 모델을 못 쓴다고 보고 넣은 값인데 Open-Meteo는 전 모델이 무료다(비상업 용도).
제주에서만 우연히 맞고 동해에서는 크게 틀렸다.

**Open-Meteo는 `models`를 지정하면 수온·조석을 응답에서 뺀다.**
그래서 `fetch_marine`이 폴백 모델로 한 번 더 호출해 빠진 필드를 채운다.
어느 필드가 폴백에서 왔는지는 `marine_source.fallback_fields`에 남는다.

**저장은 `merge=True`다.** 필드 이름을 바꿔도 옛 필드가 자동으로 사라지지 않는다.
스키마를 옮길 때는 명시적으로 지워야 한다.

**iOS는 `Codable`이 아니라 딕셔너리 접근으로 읽는다.** 새 필드를 추가해도 앱이 깨지지 않는다.
단 **파고는 기상청 `wave_height`를 우선**한다 — Open-Meteo 쪽을 고쳐도 화면에 안 나타날 수 있다.
자세한 건 `docs/ios-migration.md`.

**Open-Meteo 무료 티어는 CC BY 4.0이다.** 비상업 용도이고 출처 표기 의무가 있다.
한도는 10,000/일 · 5,000/시간 · 600/분. 현재 사용량은 이중 호출 포함 하루 약 512회.

---

## 커밋할 때

**이 저장소의 커밋은 `piriram <pyoram25@gmail.com>` 으로 남긴다.**

원격 세션 컨테이너의 전역 설정(`/root/.gitconfig`)이 `Claude <noreply@anthropic.com>`이라
**아무 설정 없이 커밋하면 author가 `Claude`로 찍힌다.** 실제로 한 번 그렇게 나가서
커밋을 되돌린 적이 있다. 저장소 로컬 설정은 새 클론이면 사라지므로 **커밋 전에 확인할 것.**

```sh
git config user.name   # piriram
git config user.email  # pyoram25@gmail.com
```

`.githooks/pre-commit`에 gitleaks 스캔이 있다. 쓰려면 `git config core.hooksPath .githooks`.

---

## 배포

`Dockerfile` → Cloud Run. `gunicorn server:app`으로 뜨고 `POST /`가 수집을 돌린다.
서비스명 `do-surf-functions` · 프로젝트 `dosurf-api` · 리전 `asia-northeast3`.
스케줄은 02:15, 05:15, … 23:15 (3시간 간격, 기상청 발표 후 받으려고 정시+15분).

자세한 절차는 [`docs/DEPLOYMENT.md`](./docs/DEPLOYMENT.md).

`firebase.json`은 `functions/` (nodejs20)를 참조하는데 **그 폴더는 없다.**
`jobs/api_functions.py`도 `firebase_functions`를 import하지만 `requirements.txt`에 없어
현재 배포 경로가 아니다.

## 문서 규칙

`CLAUDE.md` 는 이 파일(`AGENTS.md`)로 향하는 심볼릭 링크다. **내용은 `AGENTS.md` 만 수정한다.**
(2026-08-30: 레포 간 에이전트 지침 파일명을 `AGENTS.md` 로 통일)
