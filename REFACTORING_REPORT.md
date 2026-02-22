# Do-Surf Functions 코드 리팩토링 계획서

**작성일**: 2026-02-22
**대상 브랜치**: `refactoring`
**코드베이스**: Python 2,359 LOC / 12 파일 / Firebase Functions + Cloud Run

---

## 1. 목표 및 원칙

이 계획서는 **기존 동작을 전혀 변경하지 않으면서** 코드의 유지보수성을 높이는 리팩토링 방향을 제시합니다.

- **수정 범위 최소화**: 동작 변경 없이 구조만 개선
- **중복 제거**: DRY(Don't Repeat Yourself) 원칙 적용
- **가독성 향상**: 코드가 의도를 명확히 드러내도록
- **호환성 함수 정리**: 기존 인터페이스를 보존하면서 내부 구현만 정리
- **안정성 강화**: import 실패, 환경 차이 등 예외 상황 대응

---

## 2. 코드베이스 현황

### 2-1. 파일 구조 및 규모

```
do-surf-functions/
├── main.py                  (192줄) 예보 수집 진입점
├── api_functions.py         (408줄) Firebase HTTP 엔드포인트 4개
├── server.py                (128줄) 로컬 Flask 개발 서버
├── cleanup_old_forecasts.py (277줄) 데이터 정리 CLI
├── scripts/
│   ├── __init__.py          (빈 파일)
│   ├── config.py            (47줄)  설정값 로더
│   ├── firebase_utils.py    (41줄)  Firestore 초기화
│   ├── forecast_api.py      (130줄) 기상청 API 클라이언트
│   ├── open_meteo.py        (63줄)  Open-Meteo API 클라이언트
│   ├── storage.py           (551줄) Firestore CRUD (가장 복잡)
│   ├── cache_utils.py       (205줄) 인메모리 캐시 레이어
│   ├── beach_registry.py    (186줄) 해변 메타데이터 관리
│   ├── add_location.py      (131줄) 해변 등록 CLI
│   └── locations.json       (28개 해변, 7개 지역)
├── config.json              API/스케줄/스토리지 설정
├── requirements.txt         flask, firebase-admin, requests, gunicorn
└── Dockerfile               Cloud Run 배포용
```

### 2-2. Module 의존성 그래프

```
main.py ──────────┬── scripts.forecast_api
                  ├── scripts.open_meteo
                  ├── scripts.storage ──────┬── scripts.firebase_utils
                  └── scripts.config        ├── scripts.beach_registry ⚠️ 순환
                                            └── scripts.cache_utils

api_functions.py ─┬── scripts.firebase_utils
                  └── scripts.cache_utils

server.py ────────┬── scripts.forecast_api
                  ├── scripts.open_meteo
                  ├── scripts.storage
                  └── scripts.beach_registry

cleanup_old_forecasts.py ── firebase_admin (독립)
```

### 2-3. Firestore 스키마

```
regions/{region}/{beach_id}/{YYYYMMDDHHMM}  ← 예보 문서
regions/{region}/{beach_id}/_metadata        ← 해변 메타데이터
regions/{region}/_region_metadata/beaches     ← 지역별 해변 목록
_global_metadata/all_beaches                  ← 전체 해변 목록
```

### 2-4. 코드 건강 지표

| 지표 | 현재 상태 |
|------|----------|
| 중복 코드 | ~70줄 (3%) - `load_locations()` 5벌, region 정규화 12+곳 |
| Dead Code | `update_beach_metadata()`, import 후 재정의된 함수 |
| 테스트 커버리지 | 0% (테스트 파일 없음) |
| Type Hints | 일부만 적용 (`cache_utils.py`만 양호) |
| 보안 | CORS `*`, 입력 검증 없음, rate limit 없음 |

---

## 3. 발견된 문제 목록

### 🔴 HIGH - 즉시 수정 권장

#### 3-1. `load_locations()` 함수 5벌 중복

**위치**: 5개 파일에 동일 함수가 각각 정의됨

| 파일 | 라인 | 경로 처리 방식 |
|------|------|---------------|
| `main.py` | 23-28 | `os.path.dirname(__file__)` + `"scripts/locations.json"` |
| `api_functions.py` | 18-21 | `LOCATIONS_FILE` 상수 사용 |
| `beach_registry.py` | 20-25 | `os.path.dirname(__file__)` + `"locations.json"` |
| `add_location.py` | 7-9 | `os.path.dirname(__file__)` + `"locations.json"` |
| `cleanup_old_forecasts.py` | 44-54 | `os.path.dirname(__file__)` + `"scripts/locations.json"` |

**문제**: 경로 해석 방식이 미묘하게 달라 유지보수 시 불일치 위험. 한 곳만 수정하면 나머지 4곳은 구버전 유지.

**수정 방향**: `scripts/beach_registry.py`에 정규 함수를 두고, 나머지 4개 파일에서 import.

```python
# scripts/beach_registry.py (단일 출처)
_LOCATIONS_PATH = os.path.join(os.path.dirname(__file__), "locations.json")

def load_locations() -> list[dict]:
    with open(_LOCATIONS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

# main.py, api_functions.py 등
from scripts.beach_registry import load_locations
```

> `add_location.py`와 `cleanup_old_forecasts.py`는 `scripts/` 외부이므로 import 경로 주의 필요.

---

#### 3-2. `region` 정규화 로직 14곳 산재

**패턴**: `region.replace("/", "_").replace(" ", "_")`

| 파일 | 발생 횟수 |
|------|----------|
| `storage.py` | 12곳 (lines 145, 175, 222, 316, 346, 386, 418, 451, 484, 503, 523, 542) |
| `api_functions.py` | 2곳 (lines 234, 344) |

**문제**: 한 곳이라도 패턴이 다르면 Firestore 경로 불일치 → 데이터 접근 실패. 실제로 이 정규화는 Firestore collection 경로에 사용되므로 **데이터 정합성의 핵심**.

**수정 방향**:

```python
# storage.py 상단에 private 헬퍼 정의
def _sanitize_id(value: str) -> str:
    """Firestore 컬렉션/문서 ID용 문자열 정규화."""
    return value.replace("/", "_").replace(" ", "_")
```

`api_functions.py`에서도 필요하므로, 공유가 필요하면 `scripts/firebase_utils.py`에 배치.

---

#### 3-3. `storage.py` 102-104줄 들여쓰기 오류

**위치**: `storage.py:102-104`

```python
   # -------------------------        ← 3칸 (잘못됨)
# 2) Open-Meteo 데이터 병합 (개선!)   ← 0칸 (잘못됨)
# -------------------------           ← 0칸 (잘못됨)
    for r in marine:                  ← 4칸 (정상)
```

**수정**: 주석 3줄을 `for` 루프와 같은 4칸 들여쓰기로 통일.

---

#### 3-4. `ALLOWED_HOURS` 설정값 이중 관리

**위치**: `storage.py:10` vs `config.py:26`

```python
# storage.py:10 - 하드코딩
ALLOWED_HOURS = {0, 3, 6, 9, 12, 15, 18, 21}

# config.py (config.json에서 로드)
"storage": { "allowed_hours": [0, 3, 6, 9, 12, 15, 18, 21] }
```

**문제**: `config.json`을 수정해도 `storage.py`에 반영되지 않음. `main.py`는 이미 `config.py`의 `get_allowed_hours()`를 사용 중이므로 불일치 상태.

**수정 방향**:

```python
# storage.py
from .config import get_allowed_hours
ALLOWED_HOURS = set(get_allowed_hours())
```

---

#### 3-5. `server.py`가 `main.py` 로직을 통째로 복제

**위치**: `server.py:23-96` vs `main.py:54-192`

**문제**: 예보 수집 로직이 `main.py`와 `server.py`에 각각 구현되어 있음. 두 파일이 독립적으로 유지보수되므로, 한쪽에 버그 수정이 반영되면 다른 쪽은 누락될 가능성.

**수정 방향**: `server.py`에서 `main.py`의 `main()` 함수를 직접 호출하도록 변경하거나, 수집 로직을 별도 함수로 추출하여 양쪽에서 공유.

```python
# server.py
from main import main as run_collection

@app.route('/', methods=['POST', 'GET'])
def collect():
    result = run_collection()
    return jsonify(result), 200
```

---

### 🟡 MEDIUM - 개선 권장

#### 3-6. HTTP 응답 헤더 패턴 8회 반복

**위치**: `api_functions.py` 전체

```python
# 모든 응답에서 동일한 헤더 블록 반복
headers={
    "Content-Type": "application/json; charset=utf-8",
    "Access-Control-Allow-Origin": "*"
}
```

**수정 방향**: 헬퍼 함수 추출

```python
def _json_response(data: dict, status: int = 200, cache_hit: bool = False):
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Access-Control-Allow-Origin": "*",
    }
    if cache_hit:
        headers["X-Cache"] = "HIT"
    return https_fn.Response(
        json.dumps(data, ensure_ascii=False), status=status, headers=headers
    )
```

---

#### 3-7. `update_beach_metadata()` Dead Code

**위치**: `storage.py:215-256`

**분석**:
- `save_forecasts_merged()` (lines 179-203)에서 이미 메타데이터를 배치 저장에 포함
- `update_beach_metadata()`를 호출하는 곳이 코드베이스 전체에 **없음**
- 42줄의 Dead Code

**수정**: 함수 삭제. 혹시 모를 외부 호출을 위해 남기려면 `_update_beach_metadata()`로 rename.

---

#### 3-8. `get_all_beach_ids_in_region()` import 후 재정의

**위치**: `storage.py:6` (import) + `storage.py:341-363` (재정의)

```python
# storage.py:6
from .beach_registry import get_all_beach_ids_in_region  # import

# storage.py:341-363
def get_all_beach_ids_in_region(region):  # 같은 이름으로 재정의 → import 덮어씀
    ...
```

**문제**: Python에서 모듈 레벨 함수 재정의는 import를 완전히 무효화함. `beach_registry.py`의 구현은 사용되지 않고, `storage.py`의 로컬 구현만 활성.

**수정 방향**:
1. import 제거 (`from .beach_registry import get_all_beach_ids_in_region` 삭제)
2. 또는 `storage.py`의 로컬 정의를 삭제하고 `beach_registry.py` 버전 사용
3. 두 구현의 차이를 확인하고, 하나로 통일

---

#### 3-9. `get_all_beaches_in_region()` 하드코딩 fallback

**위치**: `storage.py:528-533`

```python
beach_defaults = {
    "busan": ["songjeong", "haeundae", "gwangalli"],
    "jeju": ["hyeopjae", "jungmun", "hamdeok"]
}
```

**문제**:
- `locations.json`에 7개 지역 28개 해변이 있는데 fallback은 2개 지역만 커버
- `locations.json` 업데이트 시 fallback과 불일치
- `locations.json`이 Single Source of Truth인 프로젝트에서 코드 내 하드코딩은 원칙 위반

**수정 방향**: `locations.json`에서 동적 생성

```python
def _get_beach_defaults():
    locations = load_locations()
    defaults = {}
    for loc in locations:
        region = loc["region"]
        defaults.setdefault(region, []).append(loc["beach"])
    return defaults
```

---

#### 3-10. `load_locations()` 연쇄 호출로 인한 불필요한 파일 I/O

**위치**: `api_functions.py:28, 48, 60`

```python
def get_regions_from_locations():
    locations = load_locations()  # 파일 I/O #1

def get_region_name_mapping():
    locations = load_locations()  # 파일 I/O #2 (동일 데이터)

def get_beach_name_mapping():
    locations = load_locations()  # 파일 I/O #3 (동일 데이터)
```

**문제**: 하나의 엔드포인트 처리 중 같은 JSON 파일을 최대 3번 읽음.

**수정 방향**: 모듈 레벨 캐싱

```python
import functools

@functools.lru_cache(maxsize=1)
def load_locations():
    ...
```

또는 `cache_utils.py`의 `@cached` 데코레이터 활용.

---

#### 3-11. 파도 높이 매직넘버 `+0.5`

**위치**: `storage.py:123`

```python
time_groups[dt_str]["om_wave_height"] = r.get("om_wave_height", 0) + 0.5
```

**문제**: Open-Meteo 파도 높이에 0.5m를 무조건 가산하는 이유가 코드에 문서화되지 않음. 보정값인지, 안전 마진인지, 버그인지 알 수 없음.

**수정 방향**: 최소한 주석으로 의도를 명시하고, 가능하면 `config.json`에서 관리

```python
# config.json
"storage": {
    "wave_height_offset": 0.5  // Open-Meteo 보정값 (근해 관측과의 차이 보정)
}

# storage.py
WAVE_HEIGHT_OFFSET = config.get("storage", {}).get("wave_height_offset", 0.5)
time_groups[dt_str]["om_wave_height"] = r.get("om_wave_height", 0) + WAVE_HEIGHT_OFFSET
```

---

### 🟢 LOW - 정리 권장

#### 3-12. `open_meteo.py` docstring 필드명 불일치

**위치**: `open_meteo.py:15-22`

```python
# docstring: sea_surface_temperature
# 실제 반환: "om_sea_surface_temperature"
```

**수정**: docstring을 실제 반환 키 (`om_` prefix)에 맞게 수정.

---

#### 3-13. `forecast_api.py` 모듈 레벨 API 키 로딩

**위치**: `forecast_api.py:27`

```python
AUTH_KEY = _load_api_key()  # import 시 즉시 실행 → 환경변수 없으면 ValueError
```

**문제**: 이 모듈을 직접 사용하지 않는 코드 경로(예: `api_functions.py`)에서도, import 체인에 포함되면 앱이 죽을 수 있음. 테스트 환경에서도 반드시 `KMA_API_KEY` 설정 필요.

**수정 방향**: Lazy loading

```python
_AUTH_KEY = None

def _get_auth_key():
    global _AUTH_KEY
    if _AUTH_KEY is None:
        _AUTH_KEY = _load_api_key()
    return _AUTH_KEY
```

---

#### 3-14. `main.py` 내 중복 `forecast_count` 계산

**위치**: `main.py:105, 145`

```python
# Line 105 (외부 try 블록)
forecast_count = len(picked)

# Line 145 (내부 블록에서 동일 값 재계산)
forecast_count = len(picked)
```

**수정**: 첫 번째 계산값을 재사용하도록 변수 스코프 정리.

---

#### 3-15. `firebase_utils.py` 모듈 레벨 초기화

**위치**: `firebase_utils.py:41`

```python
db = get_db()  # import 시 즉시 Firestore 연결
```

**문제**: `forecast_api.py`와 동일하게, import만으로 Firebase 초기화가 실행됨. credentials 파일이 없는 환경(CI, 테스트)에서 import 실패.

**수정 방향**: 3-13과 동일한 lazy loading 패턴 적용.

---

## 4. 리팩토링 Phase 계획

### Phase 1: Quick Wins (예상 2시간)

> 난이도 낮음, 위험도 낮음, 효과 높음. 코드 동작에 전혀 영향 없는 변경.

| # | 작업 | 파일 | 예상 시간 |
|---|------|------|----------|
| 1 | `storage.py` 들여쓰기 오류 수정 (3-3) | `storage.py:102-104` | 5분 |
| 2 | `open_meteo.py` docstring 수정 (3-12) | `open_meteo.py` | 5분 |
| 3 | 파도 높이 매직넘버에 주석 추가 (3-11) | `storage.py:123` | 5분 |
| 4 | `forecast_count` 중복 변수 정리 (3-14) | `main.py` | 10분 |
| 5 | `_sanitize_id()` 헬퍼 추출 + 14곳 교체 (3-2) | `storage.py`, `api_functions.py` | 30분 |
| 6 | `ALLOWED_HOURS` config.py로 단일화 (3-4) | `storage.py` | 15분 |
| 7 | `update_beach_metadata()` Dead Code 제거 (3-7) | `storage.py` | 10분 |

**검증**: 각 변경 후 `python -c "from scripts import storage, cache_utils"` 등 import 테스트로 문법 오류 확인.

---

### Phase 2: 중복 통합 (예상 3시간)

> `load_locations()` 5벌 통합, 함수 중복 해소. 여러 파일 동시 수정.

| # | 작업 | 영향 파일 | 예상 시간 |
|---|------|----------|----------|
| 1 | `load_locations()` 단일화 (3-1) | 5개 파일 | 60분 |
| 2 | `get_all_beach_ids_in_region()` 중복 해소 (3-8) | `storage.py`, `beach_registry.py` | 30분 |
| 3 | 하드코딩 beach fallback 제거 (3-9) | `storage.py` | 20분 |
| 4 | `load_locations()` 캐싱 적용 (3-10) | `api_functions.py` 또는 `beach_registry.py` | 20분 |
| 5 | `server.py` ↔ `main.py` 로직 통합 (3-5) | `server.py`, `main.py` | 40분 |

**`load_locations()` 통합 상세 계획**:

```
Step 1: beach_registry.py의 load_locations()을 정규 버전으로 확정
Step 2: main.py → from scripts.beach_registry import load_locations
Step 3: api_functions.py → from scripts.beach_registry import load_locations
Step 4: cleanup_old_forecasts.py → sys.path 추가 후 import 또는 별도 유지
Step 5: add_location.py → 같은 scripts/ 내이므로 from .beach_registry import load_locations
Step 6: 기존 각 파일의 load_locations() 정의 삭제
```

> `cleanup_old_forecasts.py`는 독립 스크립트이므로 `scripts/` 패키지 import가 어려울 수 있음. 이 경우만 로컬 정의 유지하되, 주석으로 정규 버전 위치를 명시.

**검증**: 모든 엔드포인트 수동 테스트, `main.py` 실행 확인.

---

### Phase 3: API 레이어 정리 (예상 2시간)

> `api_functions.py`의 반복 패턴 제거.

| # | 작업 | 파일 | 예상 시간 |
|---|------|------|----------|
| 1 | `_json_response()` 헬퍼 추출 (3-6) | `api_functions.py` | 40분 |
| 2 | CORS 헤더를 상수로 관리 | `api_functions.py` | 10분 |
| 3 | 에러 응답도 헬퍼로 통일 | `api_functions.py` | 30분 |

**수정 전후 비교**:

```python
# Before (4개 엔드포인트 × 성공+에러 = 약 8곳)
return https_fn.Response(
    json.dumps({"error": "Region not found"}, ensure_ascii=False),
    status=404,
    headers={"Content-Type": "application/json; charset=utf-8", "Access-Control-Allow-Origin": "*"}
)

# After
return _json_response({"error": "Region not found"}, status=404)
```

---

### Phase 4: 안정성 강화 (예상 2시간)

> import 시점 실패 방지, 환경 독립성 확보.

| # | 작업 | 파일 | 예상 시간 |
|---|------|------|----------|
| 1 | `forecast_api.py` API 키 lazy loading (3-13) | `forecast_api.py` | 30분 |
| 2 | `firebase_utils.py` lazy loading (3-15) | `firebase_utils.py` | 30분 |
| 3 | import 체인 정리 (순환 참조 점검) | `storage.py` ↔ `beach_registry.py` | 30분 |

**lazy loading 패턴 (공통)**:

```python
_instance = None

def get_instance():
    global _instance
    if _instance is None:
        _instance = _initialize()  # 실제 초기화
    return _instance
```

---

## 5. 리팩토링 우선순위 전체 요약

| Phase | 우선순위 | 항목 | 파일 | 난이도 | 효과 |
|-------|---------|------|------|--------|------|
| P1 | 🔴 1 | `storage.py` 들여쓰기 수정 | `storage.py` | 매우낮음 | 가독성 |
| P1 | 🔴 2 | `_sanitize_id()` 헬퍼 추출 | `storage.py`, `api_functions.py` | 낮음 | 높음 |
| P1 | 🔴 3 | `ALLOWED_HOURS` config.py 단일화 | `storage.py` | 낮음 | 높음 |
| P1 | 🔴 4 | Dead Code 제거 (`update_beach_metadata`) | `storage.py` | 매우낮음 | 정리 |
| P1 | 🔴 5 | 매직넘버 주석/상수화 | `storage.py` | 매우낮음 | 가독성 |
| P2 | 🔴 6 | `load_locations()` 5벌 통합 | 5개 파일 | 중간 | 높음 |
| P2 | 🟡 7 | `get_all_beach_ids_in_region()` 중복 해소 | `storage.py`, `beach_registry.py` | 중간 | 높음 |
| P2 | 🟡 8 | 하드코딩 beach fallback 제거 | `storage.py` | 낮음 | 중간 |
| P2 | 🟡 9 | `load_locations()` 캐싱 | `beach_registry.py` | 낮음 | 성능 |
| P2 | 🟡 10 | `server.py` ↔ `main.py` 로직 통합 | `server.py`, `main.py` | 중간 | 높음 |
| P3 | 🟡 11 | `_json_response()` 헬퍼 추출 | `api_functions.py` | 낮음 | 중간 |
| P4 | 🟢 12 | API 키 lazy loading | `forecast_api.py` | 중간 | 안정성 |
| P4 | 🟢 13 | Firebase lazy loading | `firebase_utils.py` | 중간 | 안정성 |
| P4 | 🟢 14 | import 순환 참조 정리 | `storage.py`, `beach_registry.py` | 중간 | 안정성 |
| - | 🟢 15 | `open_meteo.py` docstring 수정 | `open_meteo.py` | 매우낮음 | 가독성 |
| - | 🟢 16 | `forecast_count` 중복 변수 | `main.py` | 매우낮음 | 가독성 |

---

## 6. 변경 시 주의사항

### 절대 건드리지 않을 것

- **호환성 함수 시그니처**: `get_beach_forecast()`, `get_beach_metadata()`, `get_all_beaches_in_region()` 등 "호환성 유지" 주석이 달린 함수의 **인자/반환값 변경 금지** (iOS 클라이언트 연동)
- **`merge=True` 옵션**: Firestore 배치 저장의 `merge=True`는 데이터 안정성의 핵심
- **캐시 키 패턴**: `invalidate_pattern(f"forecast:{region}:{beach_id}")` 등의 패턴 문자열이 키 생성 로직(`_make_key()`)과 반드시 일치해야 함. `_sanitize_id()` 도입 시 캐시 키에도 동일 함수 적용 필요
- **Firestore 컬렉션 경로**: region 정규화 로직 변경 시 기존 데이터와의 호환성 필수 확인

### 검증 방법

```bash
# Phase별 최소 검증
python -c "from scripts import storage, cache_utils, config"  # import 테스트
python -c "from scripts.beach_registry import load_locations; print(len(load_locations()))"  # 28개 확인
python main.py  # 전체 수집 파이프라인 테스트 (KMA_API_KEY 필요)

# api_functions.py 엔드포인트 테스트 (Firebase emulator 또는 배포 후)
curl localhost:5001/get_all_locations
curl localhost:5001/get_regions
curl "localhost:5001/get_beaches_by_region?region=busan"
curl "localhost:5001/get_beach_info?region=busan&beach_id=4001"
```

---

## 7. 향후 개선 방향 (리팩토링 범위 밖)

리팩토링 완료 후 별도로 고려할 수 있는 개선 사항:

| 항목 | 설명 | 우선순위 |
|------|------|---------|
| 테스트 코드 작성 | pytest 기반 unit test, Firestore mock | 높음 |
| Type Hints 추가 | public 함수 시그니처에 타입 명시 | 중간 |
| 입력 검증 추가 | API 엔드포인트 query parameter validation | 중간 |
| CORS origin 제한 | `"*"` → 실제 도메인 화이트리스트 | 중간 |
| Open-Meteo 에러 핸들링 | KMA처럼 retry/fallback 로직 추가 | 낮음 |
| Rate Limiting | API 엔드포인트 요청 제한 | 낮음 |

---

**총 예상 작업 시간**: Phase 1~4 합계 약 9시간
**위험도**: 낮음 (동작 변경 없이 내부 구조만 정리)
