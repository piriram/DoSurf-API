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
  model_compare.py      파랑 모델을 Windfinder와 대조하는 도구
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
