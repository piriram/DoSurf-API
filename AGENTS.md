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
- **첨두주기는 `ecmwf_wam025`/`ecmwf_wam` 만 준다** (2026-08-30 실측).
  `best_match`·`ncep_gfswave025/016`·`gwam`·`meteofrance_wave` 는 `wave_peak_period`
  를 받아주기는 하되 값을 전부 `None` 으로 돌려준다. 폴백(`best_match`)으로도
  못 받으므로 **세 번째 호출**을 따로 한다.
  `wave_period` 는 평균주기 계열이라 서핑 앱이 쓰는 첨두주기보다 구조적으로 작다 —
  제주 대조에서 Windfinder 8.0초 대비 평균 MAE 2.6~3.1초, 첨두 1.08초였다.
  `wave.peak_period_s` 로 저장하고 출처는 `marine_source.peak_period_model` 에 남는다.
  **`period_s` 의 더 정확한 버전이 아니라 정의가 다른 별개 값이다.**
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
지점은 `sokcho`, `jeju` 두 곳이 정의돼 있다(`REFERENCE_SPOTS`).
`--out` 으로 누적해야 여러 날 비교가 쌓인다.

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

`data/model_compare.jsonl` 초기 2건(2026-08-30)은 편향·상관 분리 이전 스키마라
MAE만 있다. 롤업이 그 날짜 수를 따로 알려주고 편향제거 평균에서 제외한다.

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
